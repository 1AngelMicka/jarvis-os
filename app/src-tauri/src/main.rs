// JARVIS 2 — application de bureau : une fenêtre sur l'interface du Core local (http://localhost:8765).
//
// - Le Core n'est pas embarqué : l'application utilise celui installé par le script d'installation (`jarvis2`).
//   S'il ne tourne pas, elle le lance (sans fenêtre de console) et l'arrête en quittant.
// - L'interface est une page web distante pour l'application : elle n'a AUCUN accès aux API natives de Tauri.
// - Icône de notification (Ouvrir, Gadget, Quitter) ; fermer la fenêtre la cache ; Ctrl+Maj+J (ou Ctrl+Alt+J) la
//   ramène.
// - Protocole `jarvis://` (lot M) : liste blanche STRICTE ici (action connue, ni identifiant, ni port, ni fragment),
//   puis une seconde fois par le Core. Le lien n'est jamais exécuté par l'application : il est remis à l'interface
//   (`#jarvis=<lien>`), qui demande au Core ce qu'il permet (une action d'interface 🟢 au plus).
// - Raccourcis globaux : voix (Ctrl+Maj+Espace, sinon Ctrl+Alt+Espace) et écran (Ctrl+Maj+Impr, sinon
//   Ctrl+Alt+Impr) passent par le même protocole (`jarvis://ecouter`, `jarvis://ecran`).
// - Gadget de bureau : petite fenêtre toujours au premier plan, en bas à droite, sur la même interface
//   (`/?mode=gadget`) ; ses boutons sont des liens `jarvis://` interceptés ici.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::webview::NewWindowResponse;
use tauri::{
    AppHandle, Manager, PhysicalPosition, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// Le Core lancé par l'application (None : il tournait déjà, on n'y touche pas).
struct Core(Mutex<Option<Child>>);

/// Interface chargée (Core prêt) ; sinon le dernier lien reçu attend qu'elle le soit.
struct Etat {
    prete: Mutex<bool>,
    en_attente: Mutex<Option<String>>,
}

/// Actions permises par le protocole (même liste que `protocole.ACTIONS` du Core).
const ACTIONS: [&str; 8] = ["ouvrir", "conversation", "nouvelle", "ecouter", "ecran", "dire", "decision", "gadget"];
const LONGUEUR_MAX: usize = 2048;

fn port() -> u16 {
    std::env::var("JARVIS2_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(8765)
}

fn core_pret(port: u16) -> bool {
    let adresse = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&adresse, Duration::from_millis(300)).is_ok()
}

/// Commande `jarvis2` : dans le PATH, sinon le dossier des commandes de uv (installation par le script).
fn commande_jarvis() -> Vec<PathBuf> {
    let mut candidats = vec![PathBuf::from(if cfg!(windows) { "jarvis2.exe" } else { "jarvis2" })];
    if let Some(maison) = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }) {
        let bin = PathBuf::from(maison).join(".local").join("bin");
        candidats.push(bin.join(if cfg!(windows) { "jarvis2.exe" } else { "jarvis2" }));
    }
    candidats
}

fn lancer_core() -> Option<Child> {
    for commande in commande_jarvis() {
        let mut c = Command::new(&commande);
        c.arg("serveur");
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW : pas de console
        }
        if let Ok(enfant) = c.spawn() {
            return Some(enfant);
        }
    }
    None
}

/// Adresse servie par le PC lui-même (Core, page d'attente) : elle reste dans la fenêtre.
fn adresse_locale(url: &Url) -> bool {
    !matches!(url.scheme(), "http" | "https" | "jarvis")
        || matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "tauri.localhost" | "[::1]"))
}

/// Liste blanche du protocole : `jarvis://<action connue>[/…][?…]`, sans identifiant, port ni fragment.
/// Renvoie l'action, ou None (le lien est ignoré sans rien faire).
fn action_permise(url: &Url) -> Option<String> {
    if url.scheme() != "jarvis" || url.as_str().len() > LONGUEUR_MAX {
        return None;
    }
    if !url.username().is_empty() || url.password().is_some() || url.port().is_some() || url.fragment().is_some() {
        return None;
    }
    let action = url.host_str()?.to_ascii_lowercase();
    if url.as_str().chars().any(|c| c.is_control()) || !ACTIONS.contains(&action.as_str()) {
        return None;
    }
    Some(action)
}

/// Encodage pour un fragment d'adresse : tout sauf les caractères non réservés.
fn encoder(texte: &str) -> String {
    let mut sortie = String::with_capacity(texte.len() * 3);
    for octet in texte.bytes() {
        if octet.is_ascii_alphanumeric() || matches!(octet, b'-' | b'_' | b'.' | b'~') {
            sortie.push(octet as char);
        } else {
            sortie.push_str(&format!("%{octet:02X}"));
        }
    }
    sortie
}

fn adresse_interface(port: u16, lien: Option<&str>) -> String {
    match lien {
        Some(l) => format!("http://localhost:{port}/#jarvis={}", encoder(l)),
        None => format!("http://localhost:{port}/"),
    }
}

/// Un lien vers un autre site (« Comment installer », « Créer une clé »…) s'ouvre dans le navigateur du système :
/// la fenêtre de l'application ne quitte jamais l'interface de JARVIS.
fn ouvrir_dehors(url: &Url) {
    if !matches!(url.scheme(), "http" | "https") {
        return;
    }
    let adresse = url.as_str();
    #[cfg(windows)]
    let resultat = {
        use std::os::windows::process::CommandExt;
        Command::new("rundll32")
            .args(["url.dll,FileProtocolHandler", adresse])
            .creation_flags(0x0800_0000)
            .spawn()
    };
    #[cfg(target_os = "macos")]
    let resultat = Command::new("open").arg(adresse).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let resultat = Command::new("xdg-open").arg(adresse).spawn();
    let _ = resultat;
}

fn montrer(app: &AppHandle) {
    if let Some(f) = app.get_webview_window("principale") {
        let _ = f.show();
        let _ = f.unminimize();
        let _ = f.set_focus();
    }
}

/// Gadget de bureau : créé au premier besoin, puis montré ou caché.
fn basculer_gadget(app: &AppHandle) {
    if let Some(g) = app.get_webview_window("gadget") {
        if g.is_visible().unwrap_or(false) {
            let _ = g.hide();
        } else {
            let _ = g.show();
        }
        return;
    }
    let Ok(url) = format!("http://localhost:{}/?mode=gadget", port()).parse::<Url>() else { return };
    let poignee = app.clone();
    let construit = WebviewWindowBuilder::new(app, "gadget", WebviewUrl::External(url))
        .title("JARVIS — gadget")
        .inner_size(340.0, 168.0)
        .resizable(false)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .on_navigation(move |url| naviguer(&poignee, url))
        .on_new_window(|url, _| {
            ouvrir_dehors(&url);
            NewWindowResponse::Deny
        })
        .build();
    if let Ok(g) = construit {
        placer_en_bas_a_droite(&g);
    }
}

fn placer_en_bas_a_droite(g: &WebviewWindow) {
    if let (Ok(Some(ecran)), Ok(taille)) = (g.primary_monitor(), g.outer_size()) {
        let zone = ecran.work_area();
        let marge = (16.0 * ecran.scale_factor()) as i32;
        let x = zone.position.x + zone.size.width as i32 - taille.width as i32 - marge;
        let y = zone.position.y + zone.size.height as i32 - taille.height as i32 - marge;
        let _ = g.set_position(PhysicalPosition::new(x, y));
    }
}

/// Lien `jarvis://` reçu (système, raccourci, gadget) : vérifié, puis remis à l'interface de la fenêtre principale.
fn recevoir_lien(app: &AppHandle, url: &Url) {
    let Some(action) = action_permise(url) else { return };
    if action == "gadget" {
        basculer_gadget(app);
        return;
    }
    let etat = app.state::<Etat>();
    if !*etat.prete.lock().unwrap() {
        *etat.en_attente.lock().unwrap() = Some(url.as_str().to_string());
        montrer(app);
        return;
    }
    if let (Some(f), Ok(adresse)) =
        (app.get_webview_window("principale"), adresse_interface(port(), Some(url.as_str())).parse::<Url>())
    {
        let _ = f.navigate(adresse); // même page : seul le fragment change (pas de rechargement)
    }
    montrer(app);
}

/// Navigation d'une fenêtre : le PC reste dans la fenêtre, `jarvis://` est intercepté, le reste part dehors.
fn naviguer(app: &AppHandle, url: &Url) -> bool {
    if url.scheme() == "jarvis" {
        recevoir_lien(app, url);
        return false;
    }
    if adresse_locale(url) {
        return true;
    }
    ouvrir_dehors(url);
    false
}

/// Dictée globale (lot K3) : prévient l'interface (même cachée) que le raccourci est tenu ou relâché ; elle enregistre,
/// le Core transcrit et colle dans l'application au premier plan. La fenêtre de JARVIS ne prend pas le focus.
fn signaler_dictee(app: &AppHandle, debut: bool) {
    if !*app.state::<Etat>().prete.lock().unwrap() {
        return;
    }
    if let Some(f) = app.get_webview_window("principale") {
        let etape = if debut { "debut" } else { "fin" };
        let _ = f.eval(&format!("window.dispatchEvent(new CustomEvent('jarvis2:dictee', {{ detail: '{etape}' }}))"));
    }
}

fn main() {
    // Ctrl+Maj+J, sinon Ctrl+Alt+J si une autre application le tient déjà ; sans raccourci libre, l'application
    // démarre quand même (l'icône de notification suffit). Idem pour la voix et l'écran.
    let fenetre = [
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyJ),
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyJ),
    ];
    let voix = [
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space),
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::Space),
    ];
    let ecran = [
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::PrintScreen),
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::PrintScreen),
    ];
    // Dictée globale (lot K3) : raccourci MAINTENU (enfoncé puis relâché)
    let dictee = [
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyD),
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT | Modifiers::ALT), Code::KeyD),
    ];
    let app = tauri::Builder::default()
        // Instance unique : un lien jarvis:// ouvert par le système relance l'exécutable ; l'instance qui tourne
        // le reçoit (fonction « deep-link » du greffon) et la seconde s'arrête.
        .plugin(tauri_plugin_single_instance::init(|app, _args, _dossier| montrer(app)))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, sc, ev| {
                    if dictee.contains(sc) {
                        signaler_dictee(app, ev.state() == ShortcutState::Pressed);
                        return;
                    }
                    if ev.state() != ShortcutState::Pressed {
                        return;
                    }
                    let lien = if fenetre.contains(sc) {
                        None
                    } else if voix.contains(sc) {
                        Some("jarvis://ecouter")
                    } else if ecran.contains(sc) {
                        Some("jarvis://ecran")
                    } else {
                        return;
                    };
                    match lien.and_then(|l| l.parse::<Url>().ok()) {
                        Some(url) => recevoir_lien(app, &url),
                        None => montrer(app),
                    }
                })
                .build(),
        )
        .manage(Core(Mutex::new(None)))
        .manage(Etat { prete: Mutex::new(false), en_attente: Mutex::new(None) })
        .setup(move |app| {
            let port = port();
            if !core_pret(port) {
                let enfant = lancer_core();
                *app.state::<Core>().0.lock().unwrap() = enfant;
            }
            // Le protocole jarvis:// est déclaré par l'installeur ; en développement (et pour une installation
            // portable sous Windows et Linux), l'application le déclare elle-même pour l'utilisateur courant.
            #[cfg(any(windows, target_os = "linux"))]
            {
                let _ = app.deep_link().register_all();
            }
            let poignee = app.handle().clone();
            app.deep_link().on_open_url(move |ev| {
                for url in ev.urls() {
                    recevoir_lien(&poignee, &url);
                }
            });
            // Lien qui a lancé l'application (premier démarrage)
            if let Ok(Some(urls)) = app.deep_link().get_current() {
                if let Some(url) = urls.into_iter().find(|u| action_permise(u).is_some()) {
                    *app.state::<Etat>().en_attente.lock().unwrap() = Some(url.as_str().to_string());
                }
            }

            // Page d'attente locale, puis l'interface du Core dès qu'il répond (60 s au plus)
            let poignee = app.handle().clone();
            let principale = WebviewWindowBuilder::new(app, "principale", WebviewUrl::App("index.html".into()))
                .title("JARVIS 2")
                .inner_size(1280.0, 820.0)
                .min_inner_size(380.0, 560.0)
                .on_navigation(move |url| naviguer(&poignee, url))
                .on_new_window(|url, _| {
                    ouvrir_dehors(&url);
                    NewWindowResponse::Deny
                })
                .build()?;
            let poignee = app.handle().clone();
            thread::spawn(move || {
                let debut = Instant::now();
                while debut.elapsed() < Duration::from_secs(60) {
                    if core_pret(port) {
                        let etat = poignee.state::<Etat>();
                        let lien = etat.en_attente.lock().unwrap().take();
                        if let Ok(adresse) = adresse_interface(port, lien.as_deref()).parse() {
                            let _ = principale.navigate(adresse);
                        }
                        *etat.prete.lock().unwrap() = true;
                        return;
                    }
                    thread::sleep(Duration::from_millis(400));
                }
                let _ = principale.eval("document.body.dataset.etat = 'echec'");
            });

            let ouvrir = MenuItem::with_id(app, "ouvrir", "Ouvrir JARVIS 2", true, None::<&str>)?;
            let gadget = MenuItem::with_id(app, "gadget", "Gadget de bureau", true, None::<&str>)?;
            let quitter = MenuItem::with_id(app, "quitter", "Quitter", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&ouvrir, &gadget, &quitter])?;
            let mut icone = TrayIconBuilder::new().menu(&menu).tooltip("JARVIS 2").on_menu_event(|app, ev| {
                match ev.id().as_ref() {
                    "ouvrir" => montrer(app),
                    "gadget" => basculer_gadget(app),
                    "quitter" => app.exit(0),
                    _ => {}
                }
            });
            if let Some(image) = app.default_window_icon() {
                icone = icone.icon(image.clone());
            }
            icone.build(app)?;
            for groupe in [fenetre, voix, ecran, dictee] {
                for raccourci in groupe {
                    if app.global_shortcut().register(raccourci).is_ok() {
                        break; // le premier raccourci libre de chaque groupe suffit
                    }
                }
            }
            Ok(())
        })
        .on_window_event(|fenetre, ev| {
            if let WindowEvent::CloseRequested { api, .. } = ev {
                api.prevent_close(); // fermer = cacher ; « Quitter » dans l'icône de notification
                let _ = fenetre.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("Démarrage de l'application JARVIS impossible");

    app.run(|app, ev| {
        if let RunEvent::Exit = ev {
            if let Some(mut enfant) = app.state::<Core>().0.lock().unwrap().take() {
                let _ = enfant.kill(); // seulement le Core que l'application a lancé
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn action(lien: &str) -> Option<String> {
        action_permise(&lien.parse::<Url>().unwrap())
    }

    #[test]
    fn liste_blanche() {
        assert_eq!(action("jarvis://ouvrir/memoire").as_deref(), Some("ouvrir"));
        assert_eq!(action("JARVIS://Ecouter").as_deref(), Some("ecouter"));
        assert_eq!(action("jarvis://dire?texte=bonjour").as_deref(), Some("dire"));
        assert_eq!(action("jarvis://executer?c=rm"), None);
        assert_eq!(action("jarvis://deverrouiller"), None);
        assert_eq!(action("jarvis://moi@ouvrir/memoire"), None);
        assert_eq!(action("jarvis://ouvrir:80/memoire"), None);
        assert_eq!(action("jarvis://ouvrir/memoire#x"), None);
        assert_eq!(action("https://ouvrir/memoire"), None);
        assert_eq!(action(&format!("jarvis://dire?texte={}", "a".repeat(3000))), None);
    }

    #[test]
    fn fragment_encode() {
        assert_eq!(
            adresse_interface(8765, Some("jarvis://dire?texte=a b&c")),
            "http://localhost:8765/#jarvis=jarvis%3A%2F%2Fdire%3Ftexte%3Da%20b%26c"
        );
        assert_eq!(adresse_interface(8765, None), "http://localhost:8765/");
    }
}
