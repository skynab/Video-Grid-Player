#!/usr/bin/env bash
# build_deb.sh — wrap the PyInstaller output into a Debian .deb package.
#
# Usage:  bash packaging/linux/build_deb.sh [VERSION]
#   VERSION defaults to 1.2.0 if omitted.
#
# Prerequisites:
#   - PyInstaller has already run:  pyinstaller VideoGridPlayer.spec
#     (produces dist/VideoGridPlayer/)
#   - dpkg-deb is available (ships with dpkg on any Debian/Ubuntu system)
#
# Output: <project-root>/videogridplayer_<VERSION>_amd64.deb

set -euo pipefail

# ---------------------------------------------------------------------------
VERSION="${1:-1.2.0}"
ARCH="amd64"
PACKAGE="videogridplayer"
DEB_NAME="${PACKAGE}_${VERSION}_${ARCH}.deb"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
DIST_DIR="${PROJECT_ROOT}/dist/VideoGridPlayer"
STAGING="${PROJECT_ROOT}/deb_staging"

echo "==> Building ${DEB_NAME}"

# ---------------------------------------------------------------------------
# Sanity check
if [ ! -f "${DIST_DIR}/VideoGridPlayer" ]; then
    echo "ERROR: ${DIST_DIR}/VideoGridPlayer not found."
    echo "       Run 'pyinstaller VideoGridPlayer.spec' first."
    exit 1
fi

# ---------------------------------------------------------------------------
# Build the staging tree
rm -rf "${STAGING}"

# /DEBIAN   — package metadata
# /usr/share/VideoGridPlayer — the app bundle
# /usr/bin  — thin launcher so the user can run 'videogridplayer' from a terminal
# /usr/share/applications — .desktop entry so it appears in the app launcher
mkdir -p "${STAGING}/DEBIAN"
mkdir -p "${STAGING}/usr/share/VideoGridPlayer"
mkdir -p "${STAGING}/usr/bin"
mkdir -p "${STAGING}/usr/share/applications"

# ---------------------------------------------------------------------------
# Copy PyInstaller output
cp -r "${DIST_DIR}/." "${STAGING}/usr/share/VideoGridPlayer/"
chmod +x "${STAGING}/usr/share/VideoGridPlayer/VideoGridPlayer"

# ---------------------------------------------------------------------------
# Thin shell launcher in /usr/bin
cat > "${STAGING}/usr/bin/videogridplayer" << 'LAUNCHER'
#!/bin/sh
exec /usr/share/VideoGridPlayer/VideoGridPlayer "$@"
LAUNCHER
chmod +x "${STAGING}/usr/bin/videogridplayer"

# ---------------------------------------------------------------------------
# Desktop entry (so GNOME/KDE shows it in the app grid)
cp "${SCRIPT_DIR}/VideoGridPlayer.desktop" \
   "${STAGING}/usr/share/applications/VideoGridPlayer.desktop"

# ---------------------------------------------------------------------------
# control file — substitute the real version in
sed "s/^Version:.*/Version: ${VERSION}/" \
    "${SCRIPT_DIR}/control" > "${STAGING}/DEBIAN/control"

# dpkg-deb wants the Installed-Size in KB
INSTALLED_SIZE=$(du -sk "${STAGING}/usr" | awk '{print $1}')
echo "Installed-Size: ${INSTALLED_SIZE}" >> "${STAGING}/DEBIAN/control"

# ---------------------------------------------------------------------------
# Build the package
dpkg-deb --build --root-owner-group "${STAGING}" "${PROJECT_ROOT}/${DEB_NAME}"

echo "==> Created: ${PROJECT_ROOT}/${DEB_NAME}"
echo ""
echo "Install with:   sudo dpkg -i ${DEB_NAME}"
echo "Remove with:    sudo apt remove ${PACKAGE}"
