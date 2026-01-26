# Invoicator - Tauri Frontend

The desktop frontend for Invoicator, built with Vue.js 3, TypeScript, and Tailwind CSS, packaged as a Tauri 2 application.

## Development

```bash
# Install dependencies
npm install

# Start dev server (requires backend running separately)
npm run tauri dev
```

In dev mode, the Vite dev server proxies `/api/*` to `localhost:8000`. Start the backend first:

```bash
cd ../backend
python run_server.py
```

## Production Build

Build from the project root using Make (this handles the backend, resources, and Tauri app):

```bash
cd ..
make           # Full build: backend + Tauri app
```

Or to build only the Tauri app (after the backend is already in `src-tauri/resources/backend/`):

```bash
npm run tauri build
```

See the root [README](../README.md) for the full list of Make targets.

## Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/) + [Volar](https://marketplace.visualstudio.com/items?itemName=Vue.volar) + [Tauri](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode) + [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)
