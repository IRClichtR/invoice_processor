# Makefile — Invoicator build system
#
# Usage:
#   make              Build everything (backend + Tauri app)
#   make help         Show all available targets
#
# CI usage:
#   make resources frontend-deps
#   make tauri TAURI_ARGS="--target aarch64-apple-darwin"

.DEFAULT_GOAL := all
TAURI_ARGS ?=

# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------
ifeq ($(OS),Windows_NT)
    PLATFORM := windows
else
    UNAME_S := $(shell uname -s)
    ifeq ($(UNAME_S),Linux)
        PLATFORM := linux
    endif
    ifeq ($(UNAME_S),Darwin)
        PLATFORM := macos
    endif
endif

# ---------------------------------------------------------------------------
# Platform-specific shell helpers (used via $(call CMD,args...))
# ---------------------------------------------------------------------------
ifeq ($(PLATFORM),windows)
    RM    = powershell -Command "if (Test-Path '$(1)') { Remove-Item -Recurse -Force '$(1)' }"
    MKDIR = powershell -Command "New-Item -ItemType Directory -Force -Path '$(1)' | Out-Null"
    CP    = powershell -Command "Copy-Item -Recurse -Force '$(1)/*' '$(2)/'"
    TOUCH = powershell -Command "New-Item -ItemType File -Force -Path '$(1)' | Out-Null"
else
    RM    = rm -rf $(1)
    MKDIR = mkdir -p $(1)
    CP    = cp -r $(1)/* $(2)/
    TOUCH = touch $(1)
endif

# Vendor fetch command (platform-specific)
ifeq ($(PLATFORM),linux)
    FETCH_VENDOR = cd backend && bash scripts/fetch_deps_linux.sh
else ifeq ($(PLATFORM),macos)
    FETCH_VENDOR = cd backend && bash scripts/fetch_deps_macos.sh
else ifeq ($(PLATFORM),windows)
    FETCH_VENDOR = cd backend && powershell -ExecutionPolicy Bypass -File scripts/fetch_deps_windows.ps1
endif

# ---------------------------------------------------------------------------
# Phony targets
# ---------------------------------------------------------------------------
.PHONY: all install-python-deps vendor-deps backend resources frontend-deps \
        tauri dev dev-backend dev-frontend \
        clean clean-backend clean-vendor clean-resources clean-frontend help

# ---------------------------------------------------------------------------
# Build targets
# ---------------------------------------------------------------------------
all: tauri

install-python-deps: .build/python-deps.stamp
vendor-deps: .build/vendor-deps.stamp
backend: .build/backend.stamp
resources: .build/resources.stamp
frontend-deps: .build/frontend-deps.stamp

tauri: .build/resources.stamp .build/frontend-deps.stamp
	cd tauri-app && npm run tauri build $(TAURI_ARGS)

# ---------------------------------------------------------------------------
# Stamp-file recipes
# ---------------------------------------------------------------------------
.build:
	$(call MKDIR,.build)

.build/python-deps.stamp: backend/requirements.txt | .build
	pip install -r backend/requirements.txt pyinstaller
	$(call TOUCH,$@)

.build/vendor-deps.stamp: | .build
	$(FETCH_VENDOR)
	$(call TOUCH,$@)

.build/backend.stamp: .build/python-deps.stamp .build/vendor-deps.stamp | .build
	cd backend && pyinstaller invoice_processor.spec --noconfirm
	$(call TOUCH,$@)

.build/resources.stamp: .build/backend.stamp | .build
	$(call RM,tauri-app/src-tauri/resources/backend)
	$(call MKDIR,tauri-app/src-tauri/resources/backend)
	$(call CP,backend/dist/invoice_processor,tauri-app/src-tauri/resources/backend)
	$(call TOUCH,$@)

.build/frontend-deps.stamp: tauri-app/package-lock.json | .build
	cd tauri-app && npm ci
	$(call TOUCH,$@)

# ---------------------------------------------------------------------------
# Development
# ---------------------------------------------------------------------------
dev:
	@echo "Start development in two terminals:"
	@echo ""
	@echo "  Terminal 1 (backend):   make dev-backend"
	@echo "  Terminal 2 (frontend):  make dev-frontend"

dev-backend:
	cd backend && python run_server.py

dev-frontend:
	cd tauri-app && npm run tauri dev

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
clean: clean-backend clean-vendor clean-resources clean-frontend
	$(call RM,.build)

clean-backend:
	$(call RM,backend/dist)
	$(call RM,backend/build)

clean-vendor:
	$(call RM,backend/vendor/$(PLATFORM))

clean-resources:
	$(call RM,tauri-app/src-tauri/resources/backend)

clean-frontend:
	$(call RM,tauri-app/node_modules)

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:
	@echo "Invoicator Build System"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Build targets:"
	@echo "  all                  Full production build (default)"
	@echo "  install-python-deps  Install Python dependencies and PyInstaller"
	@echo "  vendor-deps          Fetch platform vendor binaries (tesseract, poppler)"
	@echo "  backend              Build backend with PyInstaller"
	@echo "  resources            Copy backend into Tauri resources"
	@echo "  frontend-deps        Install npm dependencies (npm ci)"
	@echo "  tauri                Build the Tauri desktop app"
	@echo ""
	@echo "Development:"
	@echo "  dev                  Print two-terminal dev instructions"
	@echo "  dev-backend          Start the backend dev server"
	@echo "  dev-frontend         Start the Tauri dev app"
	@echo ""
	@echo "Clean:"
	@echo "  clean                Remove all build artifacts"
	@echo "  clean-backend        Remove backend/dist and backend/build"
	@echo "  clean-vendor         Remove backend/vendor/$(PLATFORM)"
	@echo "  clean-resources      Remove tauri-app/src-tauri/resources/backend"
	@echo "  clean-frontend       Remove tauri-app/node_modules"
	@echo ""
	@echo "CI examples:"
	@echo "  make resources frontend-deps"
	@echo "  make tauri TAURI_ARGS=\"--target aarch64-apple-darwin\""
