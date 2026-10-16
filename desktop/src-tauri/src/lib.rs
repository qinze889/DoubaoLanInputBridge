use serde::Serialize;
use std::{
  fs,
  net::TcpListener,
  path::{Path, PathBuf},
  process::Command,
  sync::Mutex,
};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use tauri::{
  menu::{Menu, MenuItem},
  tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
  Manager, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

const DEFAULT_PORT: u16 = 8765;
const MAX_PORT: u16 = 8865;

#[derive(Default)]
struct BridgeRuntime {
  child: Mutex<Option<CommandChild>>,
  port: Mutex<Option<u16>>,
}

#[derive(Serialize)]
struct BridgeRuntimeInfo {
  running: bool,
  port: Option<u16>,
  key: String,
}

fn access_key_path() -> PathBuf {
  let root = std::env::var_os("LOCALAPPDATA")
    .map(PathBuf::from)
    .unwrap_or_else(|| PathBuf::from("."));
  root.join("DoubaoLanInputBridge").join("access_key.txt")
}

fn read_access_key() -> String {
  fs::read_to_string(access_key_path())
    .unwrap_or_default()
    .trim()
    .to_string()
}

fn find_available_port() -> Result<u16, String> {
  for port in DEFAULT_PORT..=MAX_PORT {
    if TcpListener::bind(("0.0.0.0", port)).is_ok() {
      return Ok(port);
    }
  }
  Err(format!("端口 {DEFAULT_PORT}-{MAX_PORT} 均被占用"))
}

fn spawn_bridge(app: &tauri::AppHandle, runtime: &BridgeRuntime) -> Result<u16, String> {
  let mut child_slot = runtime.child.lock().map_err(|_| "服务状态锁异常")?;
  if child_slot.is_some() {
    return runtime
      .port
      .lock()
      .map_err(|_| "端口状态锁异常")?
      .ok_or_else(|| "服务端口未知".to_string());
  }

  let port = find_available_port()?;
  let (_events, child) = app
    .shell()
    .sidecar("bridge-service")
    .map_err(|error| format!("找不到桥接服务：{error}"))?
    .args(["--server-only", "--port", &port.to_string()])
    .spawn()
    .map_err(|error| format!("启动桥接服务失败：{error}"))?;

  *child_slot = Some(child);
  *runtime.port.lock().map_err(|_| "端口状态锁异常")? = Some(port);
  Ok(port)
}

fn terminate_child(child: CommandChild) -> Result<(), String> {
  #[cfg(windows)]
  {
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let status = Command::new("taskkill")
      .args(["/PID", &child.pid().to_string(), "/T", "/F"])
      .creation_flags(CREATE_NO_WINDOW)
      .status()
      .map_err(|error| format!("无法结束服务进程树：{error}"))?;
    if status.success() {
      return Ok(());
    }
  }
  child.kill().map_err(|error| format!("停止服务失败：{error}"))
}

#[tauri::command]
fn bridge_runtime(runtime: tauri::State<BridgeRuntime>) -> Result<BridgeRuntimeInfo, String> {
  let running = runtime
    .child
    .lock()
    .map_err(|_| "服务状态锁异常")?
    .is_some();
  let port = *runtime.port.lock().map_err(|_| "端口状态锁异常")?;
  Ok(BridgeRuntimeInfo {
    running,
    port,
    key: read_access_key(),
  })
}

#[tauri::command]
fn start_bridge(app: tauri::AppHandle, runtime: tauri::State<BridgeRuntime>) -> Result<u16, String> {
  spawn_bridge(&app, &runtime)
}

#[tauri::command]
fn stop_bridge(runtime: tauri::State<BridgeRuntime>) -> Result<(), String> {
  stop_runtime(&runtime)
}

fn stop_runtime(runtime: &BridgeRuntime) -> Result<(), String> {
  let child = runtime
    .child
    .lock()
    .map_err(|_| "服务状态锁异常")?
    .take();
  if let Some(child) = child {
    terminate_child(child)?;
  }
  *runtime.port.lock().map_err(|_| "端口状态锁异常")? = None;
  Ok(())
}

#[cfg(windows)]
fn write_update_helper() -> Result<PathBuf, String> {
  let root = std::env::var_os("LOCALAPPDATA")
    .map(PathBuf::from)
    .ok_or_else(|| "无法读取 LOCALAPPDATA".to_string())?
    .join("DoubaoLanInputBridge");
  fs::create_dir_all(&root).map_err(|error| format!("无法创建更新目录：{error}"))?;
  let script = root.join("tauri-update.ps1");
  fs::write(
    &script,
    r#"param(
  [Parameter(Mandatory=$true)][int]$CurrentPid,
  [Parameter(Mandatory=$true)][string]$InstallerPath,
  [Parameter(Mandatory=$true)][string]$RestartExe,
  [Parameter(Mandatory=$true)][string]$ExpectedVersion,
  [Parameter(Mandatory=$true)][string]$LogPath
)
$ErrorActionPreference = 'Stop'
function Write-UpdateLog([string]$Message) {
  Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
}
try {
  Write-UpdateLog 'waiting for application exit'
  Wait-Process -Id $CurrentPid -Timeout 60 -ErrorAction SilentlyContinue
  $process = Start-Process -FilePath $InstallerPath -ArgumentList '/S' -PassThru -Wait -WindowStyle Hidden
  if ($process.ExitCode -ne 0) { throw "installer exit code: $($process.ExitCode)" }
  $versionPath = Join-Path (Split-Path -Parent $RestartExe) 'VERSION'
  $installed = $false
  for ($i = 0; $i -lt 240; $i++) {
    if (Test-Path -LiteralPath $versionPath) {
      $installedVersion = (Get-Content -LiteralPath $versionPath -Encoding UTF8 -Raw).Trim()
      if ($installedVersion -eq $ExpectedVersion) { $installed = $true; break }
    }
    Start-Sleep -Milliseconds 500
  }
  if (-not $installed) { throw "installer completion marker timeout: $ExpectedVersion" }
  Write-UpdateLog 'installation completed'
  for ($i = 0; $i -lt 60 -and !(Test-Path -LiteralPath $RestartExe); $i++) { Start-Sleep -Milliseconds 500 }
  if (!(Test-Path -LiteralPath $RestartExe)) { throw "installed app not found: $RestartExe" }
  Start-Process -FilePath $RestartExe
  Write-UpdateLog 'application restarted'
} catch {
  Write-UpdateLog ("update failed: " + $_.Exception.Message)
  if (Test-Path -LiteralPath $RestartExe) {
    Start-Process -FilePath $RestartExe
    Write-UpdateLog 'previous application restarted after failure'
  }
}
"#,
  )
  .map_err(|error| format!("无法写入更新助手：{error}"))?;
  Ok(script)
}

#[tauri::command]
fn install_update(app: tauri::AppHandle, installer_path: String, expected_version: String) -> Result<(), String> {
  #[cfg(not(windows))]
  {
    let _ = app;
    let _ = installer_path;
    let _ = expected_version;
    return Err("自动更新目前仅支持 Windows".to_string());
  }

  #[cfg(windows)]
  {
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
    let local_app_data = std::env::var_os("LOCALAPPDATA")
      .map(PathBuf::from)
      .ok_or_else(|| "无法读取 LOCALAPPDATA".to_string())?;
    let update_root = local_app_data.join("DoubaoLanInputBridge").join("updates");
    let installer = Path::new(&installer_path)
      .canonicalize()
      .map_err(|error| format!("更新包不存在：{error}"))?;
    let update_root = update_root
      .canonicalize()
      .map_err(|error| format!("更新目录不存在：{error}"))?;
    if !installer.starts_with(&update_root)
      || installer.extension().and_then(|value| value.to_str()) != Some("exe")
    {
      return Err("拒绝执行更新目录之外的程序".to_string());
    }
    if expected_version.is_empty()
      || !expected_version
        .chars()
        .all(|value| value.is_ascii_alphanumeric() || matches!(value, '.' | '-' | '_'))
    {
      return Err("更新版本号格式无效".to_string());
    }

    let helper = write_update_helper()?;
    let restart_exe = std::env::current_exe()
      .map_err(|error| format!("无法确定当前程序路径：{error}"))?;
    let update_log = local_app_data
      .join("DoubaoLanInputBridge")
      .join("tauri-update.log");
    Command::new("powershell.exe")
      .args([
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
      ])
      .arg(&helper)
      .arg("-CurrentPid")
      .arg(std::process::id().to_string())
      .arg("-InstallerPath")
      .arg(&installer)
      .arg("-RestartExe")
      .arg(&restart_exe)
      .arg("-ExpectedVersion")
      .arg(&expected_version)
      .arg("-LogPath")
      .arg(&update_log)
      .creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)
      .spawn()
      .map_err(|error| format!("无法启动更新助手：{error}"))?;
    app.exit(0);
    Ok(())
  }
}

fn show_main_window(app: &tauri::AppHandle) {
  if let Some(window) = app.get_webview_window("main") {
    let _ = window.unminimize();
    let _ = window.show();
    let _ = window.set_focus();
  }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
      show_main_window(app);
    }))
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_opener::init())
    .plugin(tauri_plugin_log::Builder::default().level(log::LevelFilter::Info).build())
    .manage(BridgeRuntime::default())
    .invoke_handler(tauri::generate_handler![bridge_runtime, start_bridge, stop_bridge, install_update])
    .setup(|app| {
      let main_window = if let Some(window) = app.get_webview_window("main") {
        window
      } else {
        WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
          .title("声笺")
          .inner_size(1180.0, 760.0)
          .min_inner_size(900.0, 620.0)
          .build()?
      };
      main_window.show()?;
      main_window.center()?;
      main_window.set_focus()?;

      let show_item = MenuItem::with_id(app, "show", "打开主界面", true, None::<&str>)?;
      let quit_item = MenuItem::with_id(app, "quit", "彻底退出", true, None::<&str>)?;
      let menu = Menu::with_items(app, &[&show_item, &quit_item])?;
      let app_handle = app.handle().clone();
      TrayIconBuilder::new()
        .icon(app.default_window_icon().expect("missing app icon").clone())
        .tooltip("声笺")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
          "show" => show_main_window(app),
          "quit" => app.exit(0),
          _ => {}
        })
        .on_tray_icon_event(|tray, event| {
          if let TrayIconEvent::DoubleClick {
            button: MouseButton::Left,
            ..
          } = event
          {
            show_main_window(tray.app_handle());
          }
        })
        .build(app)?;

      let hidden_window = main_window.clone();
      main_window.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
          api.prevent_close();
          let _ = hidden_window.hide();
        }
      });

      let runtime = app.state::<BridgeRuntime>();
      spawn_bridge(&app_handle, &runtime).map_err(std::io::Error::other)?;
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while running tauri application");
  app.run(|app_handle, event| {
    if matches!(event, tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit) {
      let runtime = app_handle.state::<BridgeRuntime>();
      let _ = stop_runtime(&runtime);
    }
  });
}
