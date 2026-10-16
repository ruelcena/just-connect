# just-connect

A minimal Python VNC desktop client for machines you own or have explicit
permission to access. It connects over VNC with **no username field** — only
anonymous / no-auth or VNC-password authentication.

Features:

- **Connect codes:** the built-in server generates a short code (e.g.
  `ABCD-EFGH`) and announces itself on the local network. Clients enter the
  code and the server is found automatically — no IP address to type.
- Connection dialog: connect code, or manual host/IP + port (default 5900)
  with optional password on the "Manual (IP)" tab.
- Remote view refreshed on a configurable interval (default 1 FPS).
- Keyboard forwarding, including modifiers and special keys.
- Mouse click / move forwarding from the view widget.
- Screenshot button saves the current frame as PNG.
- Remembers last host/port in a config file; never stores the password in
  plain text (memory-only by default, optional OS keyring storage). Connect
  codes are never persisted.
- Clean shutdown of sockets and threads; detects dropped connections and
  offers reconnect.
- Two pluggable backends:
  - `vncdotool` (pure Python, default, always works).
  - `tinyvnc` (optional C++ backend via pybind11).

> **Security warning:** VNC password authentication and RAW encoding are
> **unencrypted**. Anyone on the network can read the password and screen data.
> Only use this on trusted local networks, or tunnel through SSH / VPN when
> connecting over the internet. See [Security](#security) below.

## Project structure

```text
src/just_connect/
  backend.py              # VncBackend abstract interface
  vncdotool_backend.py    # pure-Python backend
  tinyvnc_backend.py      # optional TinyVNC wrapper loader
  tinyvnc_build/          # pybind11 build for TinyVNC
  discovery.py            # connect codes + LAN announcement/discovery
  worker.py               # QThread worker
  cli.py                  # command-line script
  server.py               # built-in VNC server
  app.py                  # GUI entry point
  config.py               # host/port persistence
  keyring_store.py        # optional keyring helper
  gui/                    # PySide6 widgets
tests/                    # pytest suite
```

## Install

Requires Python 3.10+ and a C++ compiler only if you build the optional TinyVNC
backend. PySide6 wheels are available for Python 3.10–3.13; the app also runs on
Python 3.14 in our testing because PySide6 6.12 ships `cp310-abi3` wheels that
load on newer interpreters.

```bash
# Create a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# Install the app
pip install -e .

# Or with the optional TinyVNC backend (requires CMake + C++ toolchain)
pip install -e ".[tinyvnc]"
python src/just_connect/tinyvnc_build/setup.py build_ext --inplace
```

## Start a local test VNC server

### TigerVNC (Linux / most platforms)

```bash
# Set a password (optional). Leave blank for no-auth / anonymous.
vncpasswd

# Start a server on display :1 (port 5901)
vncserver :1 -geometry 1280x720 -depth 24
```

Connect with the GUI on host `127.0.0.1`, port `5901`, and the password you
set.

### macOS Screen Sharing

1. Open **System Settings → General → Sharing**.
2. Turn on **Screen Sharing**.
3. Set access to **Only these users** or **All users**.
4. Note the computer name / IP. macOS listens on port 5900 by default.

### Built-in server (no third-party install needed)

just-connect now ships with its own lightweight VNC server so you don't have
to install TightVNC, TigerVNC, or macOS Screen Sharing on the remote computer.

On the computer you want to control, run:

```bash
just-connect-server
```

The server prints a **connect code** and announces itself on the local
network:

```text
==============================================
  Connect code:  ABCD-EFGH
  Share this code with the person connecting.
  They do not need this machine's IP address.
==============================================
```

The code is also used as the VNC password, so only someone you give the code
to can connect. Read the code to the person connecting over the phone or a
message — they enter it in the GUI or CLI and the server is found
automatically, no IP address needed.

Server options:

- `--host` / `--port` – listen address and port (default `0.0.0.0:5900`).
- `--code CODE` – use a specific connect code instead of a generated one.
- `--password PASS` – use a separate VNC password (the code is then only
  used for discovery, not authentication).
- `--no-auth` – allow anonymous / no-auth connections (insecure; trusted
  LANs only). This restores the pre-code behavior.
- `--no-discovery` – do not announce on the network; clients must connect
  manually by host/IP.

> **Note:** The built-in server is a desktop process, not a registered
> Windows service. Run it while logged in to the remote computer.

### In-memory test server for development

The repository also includes a minimal Python test server in `tests/vnc_server.py`:

```bash
python tests/vnc_server.py
# Server listens on port 5900 with password "secret"
```

## Usage

### GUI

```bash
python -m just_connect
# or
just-connect
```

1. Click **Connect**.
2. On the **Connect code** tab, enter the code shown by the remote
   `just-connect-server` and click OK — the server is discovered on your
   network automatically.
3. Alternatively, use the **Manual (IP)** tab to enter host/IP, port, and an
   optional password (leave blank for anonymous / no-auth servers).
4. Adjust FPS with the toolbar spinner (1–10 FPS).
5. Type in the **Send text** box and press Enter to send a string.
6. Click inside the remote view to focus it, then type or use the mouse.
7. Click **Screenshot** to save the current frame.
8. Click **Disconnect** or close the window for clean shutdown.

### CLI

With a connect code (no IP needed):

```bash
just-connect-cli --code ABCD-EFGH -o screenshot.png
```

Or the classic way with an explicit host:

```bash
just-connect-cli --host 127.0.0.1 --port 5900 --password secret -o screenshot.png
```

The CLI connects, grabs one screenshot, and types text (default `hello`).

Options:

- `--code` – connect code shown by `just-connect-server`; the server is
  auto-discovered on the local network and the code is used as the password
  unless `--password` is also given.
- `--host` – VNC host or IP (required when `--code` is not used).
- `--port` – port (default 5900).
- `--password` – VNC password; omit for anonymous.
- `-o, --output` – screenshot path (default `screenshot.png`).
- `--type` – text to type after capture (default `hello`).
- `--timeout` – connection timeout in seconds (default 10).

### Backend selection

Edit the config file:

- Windows: `%APPDATA%\just-connect\config.json`
- macOS / Linux: `~/.config/just-connect/config.json`

```json
{
  "host": "127.0.0.1",
  "port": 5900,
  "backend": "vncdotool",
  "fps": 1
}
```

Set `"backend": "tinyvnc"` after building the C++ extension. If the extension
is not available, the app automatically falls back to `vncdotool`.

## Security

VNC password authentication sends the password and all screen data in **plain
text**. Do not use it over untrusted networks.

Connect codes and discovery are designed not to weaken this:

- Codes are 8 random characters from a 32-character alphabet (~40 bits),
  generated with the `secrets` module on every server start.
- The code is **never broadcast**. Announcements contain a fresh random
  nonce and `HMAC-SHA256(code, nonce)`; clients verify the tag in constant
  time. A passive listener cannot recover the code or replay an announcement
  to impersonate the server.
- The server uses the code as its VNC password by default, so discovering a
  server without knowing its code does not get you in.
- Connect codes are kept in memory only — never written to the config file
  or keyring.

Discovery uses UDP broadcast (port 45999) and only works within the same
local network segment. Over the internet, tunnel the VNC port through SSH:

```bash
ssh -L 5900:localhost:5900 user@remote-host
```

Then connect the GUI to `127.0.0.1:5900`. The SSH tunnel encrypts both the
password and the screen stream.

Alternatively, use a VPN so the VNC traffic never leaves the encrypted tunnel.

Passwords are **never written to disk** by this app:

- The connection dialog keeps the password in memory for the current session.
- If you check "Remember password in keyring", it is stored in the OS keyring
  (Windows Credential Locker, macOS Keychain, Linux Secret Service), not in the
  config file.

## Troubleshooting

### "Server not found" when connecting by code

- `just-connect-server` is not running on the remote computer, or was
  started with `--no-discovery`.
- The two machines are not on the same local network segment (UDP broadcast
  does not cross routers or the internet). Use the **Manual (IP)** tab or an
  SSH tunnel instead.
- A firewall on either machine is blocking UDP port 45999. Allow it, or
  connect manually.
- The code was mistyped — it is 8 characters, dashes and case don't matter.

### "Connection refused"

- The VNC server is not running or is listening on a different port.
- A firewall is blocking the port.
- If connecting through an SSH tunnel, make sure the tunnel is active.

### "Server requires a password"

- The server does not allow anonymous / no-auth connections. Enter the VNC
  password in the connection dialog.

### "Authentication failed"

- The password is incorrect.
- Some servers lock out after too many failed attempts; restart the server or
  wait.

### "Connection timed out"

- The host is unreachable.
- A firewall is dropping packets instead of rejecting them.
- Increase the timeout in the connection dialog.

### UI freezes

All networking runs on a dedicated `QThread`. If the UI freezes, check the
status label: it should show **connecting** while the handshake is in progress.
A long freeze usually means the server is not responding to the handshake.

### PySide6 install fails

If you are on a very new Python version without PySide6 wheels, install Python
3.12 or 3.13 and recreate your virtual environment. The app targets 3.10+ but
is primarily tested on 3.12/3.13.

### TinyVNC build fails

The TinyVNC backend is optional. If CMake or a C++ compiler is missing, the
app still works with the vncdotool backend. To build the extension you need:

- CMake 3.15+
- A C++17 compiler
- pybind11 (`pip install ".[tinyvnc]"`)

On Windows, link against `ws2_32`. On Linux/macOS, no extra link libraries are
required.

## Windows installer (MSI)

A Windows MSI installer can be built with cx_Freeze:

```bash
pip install cx_Freeze
python setup_cxfreeze.py bdist_msi
```

The installer is written to `dist/just-connect-<version>-win64.msi`. It
installs `just-connect.exe` (GUI), `just-connect-cli.exe` (console), and
`just-connect-server.exe` (console), and creates Start Menu shortcuts for
the GUI and the server. Run `just-connect-server` on the machine you want to
control — it prints the connect code clients use to find it.

Note: the installer bundles the Python runtime, PySide6, vncdotool/Twisted,
and all dependencies. It does not include the optional TinyVNC C++ backend;
build that separately if needed.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

The test suite includes unit tests for the backend interface, worker thread
integration tests using `pytest-qt`, and an end-to-end GUI test that connects
to the in-memory `MiniVncServer` in `tests/vnc_server.py`.

## License

MIT. TinyVNC and its bundled Crypto++ sources retain their own licenses; see
`src/just_connect/tinyvnc_build/vendor/`.
