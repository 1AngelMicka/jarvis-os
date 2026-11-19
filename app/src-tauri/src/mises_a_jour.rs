// Mise à jour automatique de l'application (greffon updater de Tauri), entièrement côté Rust : l'interface est une
// page distante sans accès aux API natives.
//
// - Clé publique de signature absente (vide ou valeur d'exemple dans `plugins.updater.pubkey`) : aucune vérification,
//   et c'est dit (entrée grisée dans le menu de l'icône, message sur stderr). Idem avec `JARVIS2_MISES_A_JOUR=0`.
// - Sinon : vérification quelques secondes après le démarrage, puis une fois par jour (la date de la dernière
//   vérification est gardée dans `app_config_dir()/mises_a_jour.json`, pour ne pas revérifier à chaque relance).
// - JAMAIS d'installation seule : une version trouvée est annoncée (boîte de dialogue « Installer et redémarrer » /
//   « Plus tard », plus une entrée « Installer la version X.Y.Z… » dans le menu) ; rien ne s'installe sans clic.
//   « Plus tard » : la boîte n'est plus reproposée pour cette version, l'entrée de menu reste.
// - Réglage « Vérifier les mises à jour chaque jour » (case du menu) dans `app_config_dir()/reglages.json`, activé
//   par défaut. « Rechercher une mise à jour maintenant » vérifie à la demande.
// - Le Core lancé par l'application est arrêté avant le redémarrage (et, sous Windows, avant que l'installeur ne
//   ferme l'application).
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tauri::menu::{CheckMenuItem, Menu, MenuItem};
use tauri::{AppHandle, Manager, Wry};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::{Update, UpdaterExt};

pub const ID_QUOTIDIENNE: &str = "maj_quotidienne";
pub const ID_MAINTENANT: &str = "maj_maintenant";
pub const ID_INSTALLER: &str = "maj_installer";

const UN_JOUR: u64 = 24 * 60 * 60;
const DELAI_DEMARRAGE: Duration = Duration::from_secs(8);
const PAS_BOUCLE: Duration = Duration::from_secs(60 * 60);
const NOTES_MAX: usize = 600;
const TITRE: &str = "JARVIS 2 — mise à jour";
/// Une clé minisign encodée en base64 commence toujours ainsi (« untrusted comment: »).
const PREFIXE_CLE: &str = "dW50cnVzdGVkIGNvbW1lbnQ6";

/// Pourquoi la mise à jour automatique est désactivée (None : elle est active).
#[derive(Debug, PartialEq)]
pub enum Desactivation {
    CleAbsente,
    Variable,
}

/// État partagé : version trouvée, version remise à plus tard, entrées du menu de l'icône.
#[derive(Default)]
pub struct MisesAJour {
    trouvee: Mutex<Option<Update>>,
    plus_tard: Mutex<Option<String>>,
    en_cours: AtomicBool,
    menu: Mutex<Option<Menu<Wry>>>,
    quotidienne: Mutex<Option<CheckMenuItem<Wry>>>,
    installer: Mutex<Option<MenuItem<Wry>>>,
}

// ---------- logique pure (testée) ----------

/// Vraie clé publique de signature (pas vide, pas une valeur d'exemple).
pub fn cle_configuree(cle: &str) -> bool {
    cle.trim().starts_with(PREFIXE_CLE)
}

/// `JARVIS2_MISES_A_JOUR=0` (ou false, non, off) désactive la mise à jour automatique.
pub fn desactivee_par_variable(valeur: Option<&str>) -> bool {
    matches!(valeur.map(|v| v.trim().to_ascii_lowercase()).as_deref(), Some("0" | "false" | "non" | "off"))
}

/// Faut-il vérifier ? Jamais vérifié, ou il y a au moins 24 h (ou l'horloge a reculé).
pub fn faut_il_verifier(derniere: Option<u64>, maintenant: u64) -> bool {
    match derniere {
        None => true,
        Some(d) => d > maintenant || maintenant - d >= UN_JOUR,
    }
}

/// Réglage « vérifier chaque jour » lu dans `reglages.json` (activé par défaut, même si le fichier est illisible).
pub fn lire_quotidienne(texte: &str) -> bool {
    serde_json::from_str::<Value>(texte)
        .ok()
        .and_then(|v| v.get("mises_a_jour_quotidiennes").and_then(Value::as_bool))
        .unwrap_or(true)
}

/// Nouveau contenu de `reglages.json` : le réglage changé, les autres gardés.
pub fn ecrire_quotidienne(existant: &str, valeur: bool) -> String {
    let mut reglages = serde_json::from_str::<Value>(existant).ok().filter(Value::is_object).unwrap_or(json!({}));
    reglages["mises_a_jour_quotidiennes"] = Value::Bool(valeur);
    serde_json::to_string_pretty(&reglages).unwrap_or_default()
}

/// Date (secondes Unix) de la dernière vérification lue dans `mises_a_jour.json`.
pub fn lire_derniere(texte: &str) -> Option<u64> {
    serde_json::from_str::<Value>(texte).ok()?.get("derniere_verification")?.as_u64()
}

/// Notes de version raccourcies pour la boîte de dialogue (coupées sur un caractère entier).
pub fn tronquer(texte: &str, max: usize) -> String {
    let texte = texte.trim();
    match texte.char_indices().nth(max) {
        Some((i, _)) => format!("{}…", texte[..i].trim_end()),
        None => texte.to_string(),
    }
}

// ---------- fichiers ----------

fn fichier(app: &AppHandle, nom: &str) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join(nom))
}

fn lire(app: &AppHandle, nom: &str) -> String {
    fichier(app, nom).and_then(|f| std::fs::read_to_string(f).ok()).unwrap_or_default()
}

fn ecrire(app: &AppHandle, nom: &str, contenu: &str) {
    let Some(f) = fichier(app, nom) else { return };
    if let Some(dossier) = f.parent() {
        let _ = std::fs::create_dir_all(dossier);
    }
    if let Err(e) = std::fs::write(&f, contenu) {
        eprintln!("[mises à jour] écriture de {} impossible : {e}", f.display());
    }
}

fn maintenant() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn quotidienne_active(app: &AppHandle) -> bool {
    lire_quotidienne(&lire(app, "reglages.json"))
}

// ---------- état et menu ----------

/// La mise à jour est-elle utilisable ? Lit la clé de `plugins.updater.pubkey` et la variable d'environnement.
pub fn desactivation(app: &AppHandle) -> Option<Desactivation> {
    if desactivee_par_variable(std::env::var("JARVIS2_MISES_A_JOUR").ok().as_deref()) {
        return Some(Desactivation::Variable);
    }
    let config = app.config();
    let cle = config.plugins.0.get("updater").and_then(|u| u.get("pubkey")).and_then(Value::as_str).unwrap_or("");
    if cle_configuree(cle) {
        None
    } else {
        Some(Desactivation::CleAbsente)
    }
}

/// Entrées du menu de l'icône pour les mises à jour (à placer avant « Quitter »).
pub fn entrees_menu(app: &AppHandle) -> tauri::Result<(Option<CheckMenuItem<Wry>>, MenuItem<Wry>)> {
    match desactivation(app) {
        Some(raison) => {
            let texte = match raison {
                Desactivation::CleAbsente => "Mises à jour : clé de signature non configurée",
                Desactivation::Variable => "Mises à jour : désactivées (JARVIS2_MISES_A_JOUR=0)",
            };
            Ok((None, MenuItem::with_id(app, ID_MAINTENANT, texte, false, None::<&str>)?))
        }
        None => {
            let case = CheckMenuItem::with_id(
                app,
                ID_QUOTIDIENNE,
                "Vérifier les mises à jour chaque jour",
                true,
                quotidienne_active(app),
                None::<&str>,
            )?;
            let maintenant = MenuItem::with_id(app, ID_MAINTENANT, "Rechercher une mise à jour maintenant", true, None::<&str>)?;
            Ok((Some(case), maintenant))
        }
    }
}

/// Garde le menu (pour y ajouter « Installer la version… ») et lance la vérification de fond si elle est permise.
pub fn demarrer(app: &AppHandle, menu: Menu<Wry>, case: Option<CheckMenuItem<Wry>>) {
    let etat = app.state::<MisesAJour>();
    *etat.menu.lock().unwrap() = Some(menu);
    *etat.quotidienne.lock().unwrap() = case;
    match desactivation(app) {
        Some(Desactivation::CleAbsente) => eprintln!(
            "[mises à jour] désactivées : clé publique de signature non configurée (plugins.updater.pubkey)"
        ),
        Some(Desactivation::Variable) => eprintln!("[mises à jour] désactivées par JARVIS2_MISES_A_JOUR"),
        None => {
            let poignee = app.clone();
            thread::spawn(move || boucle(poignee));
        }
    }
}

/// Une vérification après le démarrage, puis une par jour : la boucle se réveille toutes les heures et ne vérifie
/// que si le réglage est actif et que la dernière vérification a 24 h (veille et relances comprises).
fn boucle(app: AppHandle) {
    thread::sleep(DELAI_DEMARRAGE);
    loop {
        let derniere = lire_derniere(&lire(&app, "mises_a_jour.json"));
        if quotidienne_active(&app) && faut_il_verifier(derniere, maintenant()) {
            tauri::async_runtime::block_on(verifier(app.clone(), false));
        }
        thread::sleep(PAS_BOUCLE);
    }
}

/// Clic sur une entrée du menu de l'icône qui concerne les mises à jour.
pub fn sur_menu(app: &AppHandle, id: &str) {
    match id {
        ID_QUOTIDIENNE => {
            let case = app.state::<MisesAJour>().quotidienne.lock().unwrap().clone();
            let coche = case.and_then(|c| c.is_checked().ok()).unwrap_or(true);
            ecrire(app, "reglages.json", &ecrire_quotidienne(&lire(app, "reglages.json"), coche));
        }
        ID_MAINTENANT if desactivation(app).is_none() => {
            tauri::async_runtime::spawn(verifier(app.clone(), true));
        }
        ID_INSTALLER => installer(app),
        _ => {}
    }
}

// ---------- vérification et installation ----------

async fn verifier(app: AppHandle, manuelle: bool) {
    let etat = app.state::<MisesAJour>();
    if etat.en_cours.swap(true, Ordering::SeqCst) {
        return;
    }
    let poignee = app.clone();
    let resultat = match app.updater_builder().on_before_exit(move || crate::arreter_core(&poignee)).build() {
        Ok(updater) => updater.check().await,
        Err(e) => Err(e),
    };
    etat.en_cours.store(false, Ordering::SeqCst);
    match resultat {
        Ok(Some(update)) => {
            ecrire(&app, "mises_a_jour.json", &json!({ "derniere_verification": maintenant() }).to_string());
            annoncer(&app, update, manuelle);
        }
        Ok(None) => {
            ecrire(&app, "mises_a_jour.json", &json!({ "derniere_verification": maintenant() }).to_string());
            if manuelle {
                let version = app.package_info().version.to_string();
                informer(&app, &format!("JARVIS 2 est à jour (version {version})."), MessageDialogKind::Info);
            }
        }
        Err(e) => {
            eprintln!("[mises à jour] vérification impossible : {e}");
            if manuelle {
                informer(&app, &format!("Vérification impossible : {e}"), MessageDialogKind::Warning);
            }
        }
    }
}

/// Version trouvée : entrée de menu (toujours) et boîte de dialogue (sauf si l'utilisateur a déjà dit « Plus tard »
/// pour cette version, hors recherche manuelle).
fn annoncer(app: &AppHandle, update: Update, manuelle: bool) {
    let etat = app.state::<MisesAJour>();
    let version = update.version.clone();
    eprintln!("[mises à jour] version {version} disponible");
    ajouter_entree_installer(app, &version);
    let notes = update.body.as_deref().map(|n| tronquer(n, NOTES_MAX)).unwrap_or_default();
    *etat.trouvee.lock().unwrap() = Some(update);
    if !manuelle && etat.plus_tard.lock().unwrap().as_deref() == Some(version.as_str()) {
        return;
    }
    let mut texte = format!("La version {version} de JARVIS 2 est disponible (installée : {}).", app.package_info().version);
    if !notes.is_empty() {
        texte.push_str("\n\n");
        texte.push_str(&notes);
    }
    let poignee = app.clone();
    app.dialog()
        .message(texte)
        .title(TITRE)
        .buttons(MessageDialogButtons::OkCancelCustom("Installer et redémarrer".into(), "Plus tard".into()))
        .show(move |installer_maintenant| {
            if installer_maintenant {
                installer(&poignee);
            } else {
                *poignee.state::<MisesAJour>().plus_tard.lock().unwrap() = Some(version);
            }
        });
}

/// Copie de l'entrée « Installer… » : les appels au menu passent par le fil principal, on ne les fait jamais en
/// tenant un verrou (le gestionnaire du menu, sur ce fil, peut le demander).
fn entree_installer(app: &AppHandle) -> Option<MenuItem<Wry>> {
    app.state::<MisesAJour>().installer.lock().unwrap().clone()
}

fn regler_entree(app: &AppHandle, texte: String, active: bool) {
    if let Some(e) = entree_installer(app) {
        let _ = e.set_text(texte);
        let _ = e.set_enabled(active);
    }
}

fn ajouter_entree_installer(app: &AppHandle, version: &str) {
    let texte = format!("Installer la version {version}…");
    if entree_installer(app).is_some() {
        regler_entree(app, texte, true);
        return;
    }
    let menu = app.state::<MisesAJour>().menu.lock().unwrap().clone();
    let (Some(menu), Ok(nouvelle)) = (menu, MenuItem::with_id(app, ID_INSTALLER, texte, true, None::<&str>)) else {
        return;
    };
    // Juste avant « Quitter » (dernière entrée)
    let position = menu.items().map(|i| i.len().saturating_sub(1)).unwrap_or(0);
    if menu.insert(&nouvelle, position).is_ok() {
        *app.state::<MisesAJour>().installer.lock().unwrap() = Some(nouvelle);
    }
}

/// Après un clic explicite seulement : téléchargement, vérification de la signature, installation, redémarrage.
fn installer(app: &AppHandle) {
    let Some(update) = app.state::<MisesAJour>().trouvee.lock().unwrap().clone() else { return };
    regler_entree(app, format!("Installation de la version {}…", update.version), false);
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        eprintln!("[mises à jour] téléchargement de la version {}", update.version);
        // Sous Windows, l'installeur ferme l'application lui-même (le Core est arrêté juste avant) puis la relance.
        match update.download_and_install(|_, _| {}, || {}).await {
            Ok(()) => {
                crate::arreter_core(&app);
                app.restart();
            }
            Err(e) => {
                eprintln!("[mises à jour] installation impossible : {e}");
                regler_entree(&app, format!("Installer la version {}…", update.version), true);
                informer(&app, &format!("Installation impossible : {e}"), MessageDialogKind::Error);
            }
        }
    });
}

fn informer(app: &AppHandle, texte: &str, nature: MessageDialogKind) {
    app.dialog().message(texte).title(TITRE).kind(nature).show(|_| {});
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cle_absente_ou_exemple() {
        assert!(!cle_configuree(""));
        assert!(!cle_configuree("   "));
        assert!(!cle_configuree("CLE_PUBLIQUE_A_FOURNIR"));
        assert!(!cle_configuree("<clé publique>"));
        assert!(cle_configuree("dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEFCQ0QK"));
    }

    #[test]
    fn variable_d_environnement() {
        assert!(desactivee_par_variable(Some("0")));
        assert!(desactivee_par_variable(Some(" OFF ")));
        assert!(desactivee_par_variable(Some("non")));
        assert!(!desactivee_par_variable(Some("1")));
        assert!(!desactivee_par_variable(None));
    }

    #[test]
    fn decision_de_verifier() {
        let t = 1_800_000_000;
        assert!(faut_il_verifier(None, t));
        assert!(!faut_il_verifier(Some(t - 3600), t));
        assert!(!faut_il_verifier(Some(t - UN_JOUR + 1), t));
        assert!(faut_il_verifier(Some(t - UN_JOUR), t));
        assert!(faut_il_verifier(Some(t + 3600), t)); // horloge reculée
    }

    #[test]
    fn reglage_quotidien() {
        assert!(lire_quotidienne(""));
        assert!(lire_quotidienne("pas du json"));
        assert!(lire_quotidienne("{}"));
        assert!(!lire_quotidienne(r#"{"mises_a_jour_quotidiennes": false}"#));
        let ecrit = ecrire_quotidienne(r#"{"autre": 3}"#, false);
        assert!(!lire_quotidienne(&ecrit));
        assert!(ecrit.contains("\"autre\": 3"));
        assert!(lire_quotidienne(&ecrire_quotidienne("[1]", true)));
    }

    #[test]
    fn derniere_verification() {
        assert_eq!(lire_derniere(r#"{"derniere_verification": 42}"#), Some(42));
        assert_eq!(lire_derniere("{}"), None);
        assert_eq!(lire_derniere(""), None);
    }

    #[test]
    fn notes_tronquees() {
        assert_eq!(tronquer("  court  ", 10), "court");
        assert_eq!(tronquer("éèàçùéèàçù", 4), "éèàç…");
        assert_eq!(tronquer("abcd", 4), "abcd");
    }
}
