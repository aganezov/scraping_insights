UV          ?= uv
RUN         ?= $(UV) run
PYTHON      ?= $(RUN) python
VERSION     := $(shell cat packaging/VERSION)
APP_NAME    := Insight Mine
DIST_DIR    := dist
GUI_SPEC    := packaging/pyinstaller_gui.spec
CLI_SPEC    := packaging/pyinstaller_cli.spec
ICON        := packaging/app.icns

ENV_FILE    ?= .env

.PHONY: version sync sync-gui setup-gui run-gui update-source-gui sync-app test gui-smoke gui-e2e-free icon cli gui app clean distclean

sync:
	$(UV) sync

sync-gui:
	$(UV) sync --extra gui

setup-gui:
	$(UV) python install 3.11
	$(UV) sync --extra gui

run-gui:
	$(RUN) insight-mine-gui --env $(ENV_FILE)

update-source-gui:
	git pull --ff-only
	$(UV) sync --extra gui

sync-app:
	$(UV) sync --extra gui --extra packaging

test:
	$(RUN) pytest

gui-smoke:
	$(RUN) insight-mine-gui-smoke --scenario fake-happy --report tmp/gui-smoke-report.json

gui-e2e-free:
	$(RUN) insight-mine-gui-smoke --scenario real-youtube-free --env $(ENV_FILE) --report tmp/gui-e2e-free-report.json

version:
	@echo $(VERSION)

icon: $(ICON)

$(ICON): packaging/gen_icon.py
	$(PYTHON) packaging/gen_icon.py

cli:
	$(PYTHON) -m PyInstaller --noconfirm --clean $(CLI_SPEC)

gui: $(ICON) cli
	$(PYTHON) -m PyInstaller --noconfirm --clean $(GUI_SPEC)
	@mkdir -p $(DIST_DIR)
	@if [ -d "$(DIST_DIR)/$(APP_NAME).app" ]; then \
	  rm -rf "$(DIST_DIR)/$(APP_NAME)-$(VERSION).app"; \
	  cp -R "$(DIST_DIR)/$(APP_NAME).app" "$(DIST_DIR)/$(APP_NAME)-$(VERSION).app"; \
	fi

app: gui

clean:
	rm -rf build
	@if [ -d "$(DIST_DIR)" ]; then \
	  find $(DIST_DIR) -maxdepth 1 -name "$(APP_NAME).app" -print0 2>/dev/null | xargs -0 rm -rf --; \
	fi

distclean: clean
	rm -rf $(DIST_DIR)
