PYTHON      ?= python3
VERSION     := $(shell cat packaging/VERSION)
APP_NAME    := Insight Mine
DIST_DIR    := dist
GUI_SPEC    := packaging/pyinstaller_gui.spec
CLI_SPEC    := packaging/pyinstaller_cli.spec
ICON        := packaging/app.icns

.PHONY: version icon cli gui app clean distclean

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

