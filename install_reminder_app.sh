#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOCAL_BIN="${HOME}/.local/bin"
APPLICATIONS_DIR="${HOME}/.local/share/applications"
LAUNCHER_PATH="${LOCAL_BIN}/reminder-app"
DESKTOP_PATH="${APPLICATIONS_DIR}/reminder.desktop"
ICON_PATH="${SCRIPT_DIR}/assets/reminder_icon.svg"

mkdir -p "${LOCAL_BIN}" "${APPLICATIONS_DIR}"

cat > "${LAUNCHER_PATH}" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
cd "${SCRIPT_DIR}"
exec "${PYTHON_BIN}" -m reminder
LAUNCHER
chmod +x "${LAUNCHER_PATH}"

cat > "${DESKTOP_PATH}" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=Any Planner
Comment=タスクプランナーを起動します
Exec=${LAUNCHER_PATH}
Icon=${ICON_PATH}
Terminal=false
Categories=Utility;
StartupNotify=true
DESKTOP
chmod +x "${DESKTOP_PATH}"

cat <<MSG
インストール完了:
- ランチャー: ${LAUNCHER_PATH}
- デスクトップエントリ: ${DESKTOP_PATH}

アプリ一覧に「Any Planner」が表示されます。
表示されない場合は一度ログアウト/ログインするか、
デスクトップ環境のキャッシュ更新を行ってください。
MSG
