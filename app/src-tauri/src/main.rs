// JARVIS 2 — application de bureau : une fenêtre sur l'interface du Core local (http://localhost:8765).
//
// - Le Core n'est pas embarqué : l'application utilise celui installé par le script d'installation (`jarvis2`).
//   S'il ne tourne pas, elle le lance (sans fenêtre de console) et l'arrête en quittant.
// - L'interface est une page web distante pour l'application : elle n'a AUCUN accès aux API natives de Tauri.
// - Icône de notification (Ouvrir, Quitter) ; fermer la fenêtre la cache ; Ctrl+Maj+J (ou Ctrl+Alt+J) la ramène.
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
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

/// Le Core lancé par l'application (None : il tournait déjà, on n'y touche pas).
struct Core(Mutex<Option<Child>>);

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
    !matches!(url.scheme(), "http" | "https")
        || matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "tauri.localhost" | "[::1]"))
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

fn main() {
    // Ctrl+Maj+J, sinon Ctrl+Alt+J si une autre application le tient déjà ; sans raccourci libre, l'application
    // démarre quand même (l'icône de notification suffit).
    let raccourcis = [
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyJ),
        Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyJ),
    ];
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _dossier| montrer(app)))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, sc, ev| {
                    if raccourcis.contains(sc) && ev.state() == ShortcutState::Pressed {
                        montrer(app);
                    }
                })
                .build(),
        )
        .manage(Core(Mutex::new(None)))
        .setup(move |app| {
            let port = port();
            if !core_pret(port) {
                let enfant = lancer_core();
                *app.state::<Core>().0.lock().unwrap() = enfant;
            }
            // Page d'attente locale, puis l'interface du Core dès qu'il répond (60 s au plus)
            let constructeur = WebviewWindowBuilder::new(app, "principale", WebviewUrl::App("index.html".into()));
            // « Dis Jarvis » en fond : fenêtre cachée, la page n'est ni ralentie ni mise en sommeil (WebView2 ;
            // les trois premiers drapeaux sont ceux que Tauri passe par défaut)
            #[cfg(windows)]
            let constructeur = constructeur.additional_browser_args(
                "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection \
                 --disable-background-timer-throttling --disable-renderer-backgrounding \
                 --disable-backgrounding-occluded-windows",
            );
            let fenetre = constructeur
                .title("JARVIS 2")
                .inner_size(1280.0, 820.0)
                .min_inner_size(380.0, 560.0)
                .on_navigation(|url| {
                    if adresse_locale(url) {
                        return true;
                    }
                    ouvrir_dehors(url);
                    false
                })
                .on_new_window(|url, _| {
                    ouvrir_dehors(&url);
                    NewWindowResponse::Deny
                })
                .build()?;
            thread::spawn(move || {
                let debut = Instant::now();
                while debut.elapsed() < Duration::from_secs(60) {
                    if core_pret(port) {
                        let url = format!("http://localhost:{port}/");
                        if let Ok(adresse) = url.parse() {
                            let _ = fenetre.navigate(adresse);
                        }
                        return;
                    }
                    thread::sleep(Duration::from_millis(400));
                }
                let _ = fenetre.eval("document.body.dataset.etat = 'echec'");
            });

            let ouvrir = MenuItem::with_id(app, "ouvrir", "Ouvrir JARVIS 2", true, None::<&str>)?;
            let quitter = MenuItem::with_id(app, "quitter", "Quitter", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&ouvrir, &quitter])?;
            let mut icone = TrayIconBuilder::new().menu(&menu).tooltip("JARVIS 2").on_menu_event(|app, ev| {
                match ev.id().as_ref() {
                    "ouvrir" => montrer(app),
                    "quitter" => app.exit(0),
                    _ => {}
                }
            });
            if let Some(image) = app.default_window_icon() {
                icone = icone.icon(image.clone());
            }
            icone.build(app)?;
            for raccourci in raccourcis {
                if app.global_shortcut().register(raccourci).is_ok() {
                    break; // le premier raccourci libre suffit
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
