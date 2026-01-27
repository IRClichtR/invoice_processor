// Copyright 2026 Floriane TUERNAL SABOTINOV
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

use std::process::Child;
#[cfg(not(debug_assertions))]
use std::process::Command;
use std::sync::Mutex;
use tauri::{Emitter, Manager, RunEvent};

const BACKEND_PORT: u16 = 8000;
const BACKEND_HOST: &str = "127.0.0.1";

/// Holds the backend child process handle for lifecycle management.
struct BackendProcess(Mutex<Option<Child>>);

/// Resolve the path to the backend executable inside bundled resources.
#[cfg(not(debug_assertions))]
fn backend_exe_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Failed to resolve resource dir: {e}"))?;

    let backend_dir = resource_dir.join("backend");

    #[cfg(target_os = "windows")]
    let exe_name = "invoice_processor.exe";
    #[cfg(not(target_os = "windows"))]
    let exe_name = "invoice_processor";

    let exe_path = backend_dir.join(exe_name);
    if !exe_path.exists() {
        return Err(format!("Backend executable not found at {}", exe_path.display()));
    }
    Ok(exe_path)
}

/// Spawn the backend process with the correct working directory and env vars.
#[cfg(not(debug_assertions))]
fn spawn_backend(app: &tauri::AppHandle) -> Result<Child, String> {
    let exe_path = backend_exe_path(app)?;
    let backend_dir = exe_path
        .parent()
        .ok_or("Cannot determine backend directory")?
        .to_path_buf();

    // Use Tauri's app_data_dir for persistent storage
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to resolve app data dir: {e}"))?;

    // Ensure data dir exists
    std::fs::create_dir_all(&data_dir)
        .map_err(|e| format!("Failed to create data dir: {e}"))?;

    log::info!(
        "Spawning backend: exe={}, cwd={}, data_dir={}",
        exe_path.display(),
        backend_dir.display(),
        data_dir.display()
    );

    Command::new(&exe_path)
        .current_dir(&backend_dir)
        .env("DATA_DIR", data_dir.to_string_lossy().to_string())
        .env("PORT", BACKEND_PORT.to_string())
        .env("HOST", BACKEND_HOST)
        .spawn()
        .map_err(|e| format!("Failed to spawn backend: {e}"))
}

/// Poll the health endpoint until the backend is ready (max ~30 seconds).
#[cfg(not(debug_assertions))]
async fn wait_for_backend_ready() -> Result<(), String> {
    let url = format!("http://{}:{}/health", BACKEND_HOST, BACKEND_PORT);
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(2))
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {e}"))?;

    for attempt in 1..=60 {
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => {
                log::info!("Backend ready after {} attempts", attempt);
                return Ok(());
            }
            Ok(resp) => {
                log::debug!("Backend not ready (status {}), attempt {}/60", resp.status(), attempt);
            }
            Err(_) => {
                log::debug!("Backend not reachable, attempt {}/60", attempt);
            }
        }
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }

    Err("Backend did not become ready within 30 seconds".to_string())
}

/// Tauri command: check if the backend is healthy.
#[tauri::command]
async fn check_backend_health() -> Result<bool, String> {
    let url = format!("http://{}:{}/health", BACKEND_HOST, BACKEND_PORT);
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .build()
        .map_err(|e| format!("HTTP client error: {e}"))?;

    match client.get(&url).send().await {
        Ok(resp) => Ok(resp.status().is_success()),
        Err(_) => Ok(false),
    }
}

/// Tauri command: return the backend base URL for the frontend.
#[tauri::command]
fn get_backend_url() -> String {
    format!("http://{}:{}", BACKEND_HOST, BACKEND_PORT)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(BackendProcess(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![check_backend_health, get_backend_url])
        .setup(|app| {
            let handle = app.handle().clone();

            #[cfg(debug_assertions)]
            {
                // Dev mode: don't spawn backend, just check if it's already running
                log::info!("Dev mode: skipping backend spawn, checking if backend is running...");
                tauri::async_runtime::spawn(async move {
                    let url = format!("http://{}:{}/health", BACKEND_HOST, BACKEND_PORT);
                    let client = reqwest::Client::builder()
                        .timeout(std::time::Duration::from_secs(2))
                        .build()
                        .unwrap();

                    match client.get(&url).send().await {
                        Ok(resp) if resp.status().is_success() => {
                            log::info!("Dev backend already running");
                            let _ = handle.emit("backend-ready", ());
                        }
                        _ => {
                            log::warn!(
                                "Dev backend not detected at {}:{}. Start it manually: cd backend && python run_server.py",
                                BACKEND_HOST, BACKEND_PORT
                            );
                            let _ = handle.emit(
                                "backend-error",
                                "Backend not running. Start it manually: cd backend && python run_server.py",
                            );
                        }
                    }
                });
            }

            #[cfg(not(debug_assertions))]
            {
                // Production mode: spawn and wait for backend
                match spawn_backend(&handle) {
                    Ok(child) => {
                        let state = handle.state::<BackendProcess>();
                        *state.0.lock().unwrap() = Some(child);
                        log::info!("Backend process spawned, waiting for ready...");

                        tauri::async_runtime::spawn(async move {
                            match wait_for_backend_ready().await {
                                Ok(()) => {
                                    log::info!("Backend is ready");
                                    let _ = handle.emit("backend-ready", ());
                                }
                                Err(e) => {
                                    log::error!("Backend failed to start: {}", e);
                                    let _ = handle.emit("backend-error", e);
                                }
                            }
                        });
                    }
                    Err(e) => {
                        log::error!("Failed to spawn backend: {}", e);
                        let _ = handle.emit("backend-error", e);
                    }
                }
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // Kill the backend process on exit
                let state = app_handle.state::<BackendProcess>();
                let mut guard = match state.0.lock() {
                    Ok(g) => g,
                    Err(_) => return,
                };
                if let Some(ref mut child) = *guard {
                    log::info!("Shutting down backend process...");
                    let _ = child.kill();
                    let _ = child.wait();
                    log::info!("Backend process terminated");
                }
            }
        });
}
