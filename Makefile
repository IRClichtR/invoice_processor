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
# Python virtual environment
# ---------------------------------------------------------------------------
VENV_DIR := backend/venv

ifeq ($(PLATFORM),windows)
    VENV_BIN    := $(VENV_DIR)/Scripts
    SYS_PYTHON  := python
else
    VENV_BIN    := $(VENV_DIR)/bin
    SYS_PYTHON  := python3
endif

PIP         := $(CURDIR)/$(VENV_BIN)/pip
PYTHON      := $(CURDIR)/$(VENV_BIN)/python
PYINSTALLER := $(CURDIR)/$(VENV_BIN)/pyinstaller

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

# System dependency check (used as pre-flight guard)
ifeq ($(PLATFORM),windows)
    CHECK_TESSERACT = where tesseract >NUL 2>&1
else
    CHECK_TESSERACT = command -v tesseract >/dev/null 2>&1
endif

# Packages installed by `make setup`
LINUX_DEPS := tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra poppler-utils \
              libwebkit2gtk-4.1-dev libayatana-appindicator3-dev librsvg2-dev patchelf \
              libfuse2

# ---------------------------------------------------------------------------
# Phony targets
# ---------------------------------------------------------------------------
.PHONY: all setup venv install-python-deps vendor-deps backend resources frontend-deps \
        tauri dev dev-backend dev-frontend \
        clean clean-venv clean-backend clean-vendor clean-resources clean-frontend help

# ---------------------------------------------------------------------------
# Setup — install system build dependencies
# ---------------------------------------------------------------------------
setup:
ifeq ($(PLATFORM),linux)
	@echo "The following packages will be installed via apt:"
	@echo "  $(LINUX_DEPS)"
	@echo ""
	@if [ "$(CONFIRM)" != "1" ]; then \
		printf "Continue? [Y/n] "; \
		read ans; \
		case "$$ans" in [nN]*) echo "Aborted."; exit 1;; esac; \
	fi
	@if [ "$$(id -u)" = "0" ]; then \
		apt-get update && apt-get install -y $(LINUX_DEPS); \
	else \
		sudo apt-get update && sudo apt-get install -y $(LINUX_DEPS); \
	fi
else ifeq ($(PLATFORM),macos)
	@echo "The following packages will be installed via Homebrew:"
	@echo "  tesseract poppler"
	@echo ""
	@if [ "$(CONFIRM)" != "1" ]; then \
		printf "Continue? [Y/n] "; \
		read ans; \
		case "$$ans" in [nN]*) echo "Aborted."; exit 1;; esac; \
	fi
	brew install tesseract poppler
else ifeq ($(PLATFORM),windows)
	@echo The following packages will be installed via Chocolatey:
	@echo   tesseract
	choco install tesseract -y
endif
	@echo System build dependencies installed successfully.

# ---------------------------------------------------------------------------
# Build targets
# ---------------------------------------------------------------------------
all: tauri

venv: .build/venv.stamp
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

.build/venv.stamp: | .build
	$(SYS_PYTHON) -m venv $(VENV_DIR)
	$(call TOUCH,$@)

.build/python-deps.stamp: backend/requirements.txt .build/venv.stamp | .build
	$(PIP) install -r backend/requirements.txt pyinstaller
	$(call TOUCH,$@)

.build/vendor-deps.stamp: | .build
	@$(CHECK_TESSERACT) || \
		{ echo ""; \
		  echo "ERROR: System build dependencies not found (tesseract, poppler)."; \
		  echo "Run 'make setup' to install them, then retry."; \
		  echo ""; \
		  exit 1; }
	$(FETCH_VENDOR)
	$(call TOUCH,$@)

.build/backend.stamp: .build/python-deps.stamp .build/vendor-deps.stamp | .build
	cd backend && $(PYINSTALLER) invoice_processor.spec --noconfirm
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

dev-backend: .build/python-deps.stamp
	cd backend && $(PYTHON) run_server.py

dev-frontend:
	cd tauri-app && npm run tauri dev

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
clean: clean-backend clean-vendor clean-resources clean-frontend clean-venv
	$(call RM,.build)

clean-venv:
	$(call RM,$(VENV_DIR))

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
	@echo "Setup:"
	@echo "  setup                Install system build dependencies (tesseract, poppler, ...)"
	@echo "                       Use CONFIRM=1 to skip the interactive prompt"
	@echo ""
	@echo "Build targets:"
	@echo "  all                  Full production build (default)"
	@echo "  venv                 Create Python virtual environment"
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
	@echo "  clean-venv           Remove Python virtual environment"
	@echo "  clean-backend        Remove backend/dist and backend/build"
	@echo "  clean-vendor         Remove backend/vendor/$(PLATFORM)"
	@echo "  clean-resources      Remove tauri-app/src-tauri/resources/backend"
	@echo "  clean-frontend       Remove tauri-app/node_modules"
	@echo ""
	@echo "CI examples:"
	@echo "  make resources frontend-deps"
	@echo "  make tauri TAURI_ARGS=\"--target aarch64-apple-darwin\""
