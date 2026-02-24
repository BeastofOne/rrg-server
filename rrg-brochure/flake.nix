{
  description = "RRG Brochure Microservice — persistent Flask container with LangGraph + Playwright/Chromium";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, poetry2nix, flake-utils }:
    let
      lib = nixpkgs.lib;

      # Docker images must contain Linux binaries
      linuxSystem = "x86_64-linux";
      linuxPkgs = import nixpkgs {
        system = linuxSystem;
        config.allowUnfreePredicate = pkg:
          builtins.elem (lib.getName pkg) [ "claude-code" ];
      };

      p2nix = poetry2nix.lib.mkPoetry2Nix { pkgs = linuxPkgs; };

      # Chromium/Playwright system dependencies for LD_LIBRARY_PATH
      playwrightDeps = with linuxPkgs; [
        # Core graphics (shared with PDF rendering)
        pango
        cairo
        gdk-pixbuf
        glib
        harfbuzz
        fontconfig
        freetype
        # X11 (Chromium needs these even in headless mode)
        xorg.libX11
        xorg.libXcomposite
        xorg.libXdamage
        xorg.libXext
        xorg.libXfixes
        xorg.libXrandr
        xorg.libxcb
        # Additional Chromium dependencies
        nss
        nspr
        alsa-lib
        at-spi2-atk
        cups
        libdrm
        mesa
        dbus
        expat
        libxkbcommon
        gtk3
        # Misc
        libffi
        zlib
      ];

      # Python environment from poetry.lock
      pythonEnv = p2nix.mkPoetryEnv {
        projectDir = self;
        python = linuxPkgs.python312;
        preferWheels = true;
        # No overrides needed — Playwright driver must stay intact.
        # PLAYWRIGHT_BROWSERS_PATH env var tells it where Nix's Chromium is.
      };

      # Application source — all Python files + templates + static assets
      appSrc = linuxPkgs.runCommand "rrg-brochure-src" {} ''
        mkdir -p $out/app/templates/static
        cp ${./server.py} $out/app/server.py
        cp ${./graph.py} $out/app/graph.py
        cp ${./brochure_pdf.py} $out/app/brochure_pdf.py
        cp ${./photo_scraper.py} $out/app/photo_scraper.py
        cp ${./photo_search_pdf.py} $out/app/photo_search_pdf.py
        cp ${./claude_llm.py} $out/app/claude_llm.py
        cp ${./templates/brochure.html} $out/app/templates/brochure.html
        cp -r ${./templates/static}/* $out/app/templates/static/
      '';

      # Fonts for PDF rendering
      fontConfig = linuxPkgs.makeFontsConf {
        fontDirectories = [
          linuxPkgs.liberation_ttf
          linuxPkgs.noto-fonts
        ];
      };

      # Build LD_LIBRARY_PATH for Chromium's shared libraries
      ldLibraryPath = lib.makeLibraryPath playwrightDeps;

    in
    {
      # Docker image — always targets x86_64-linux
      packages.x86_64-linux.dockerImage = linuxPkgs.dockerTools.buildLayeredImage {
        name = "rrg-brochure";
        tag = "latest";

        contents = [
          pythonEnv
          linuxPkgs.claude-code
          linuxPkgs.coreutils
          linuxPkgs.bashInteractive
          linuxPkgs.cacert
          linuxPkgs.liberation_ttf
          linuxPkgs.noto-fonts
          # Playwright + Chromium from nixpkgs (pre-bundled with all deps)
          linuxPkgs.playwright-driver.browsers-chromium
          appSrc
        ] ++ playwrightDeps;

        config = {
          Cmd = [ "${pythonEnv}/bin/python" "/app/server.py" ];
          ExposedPorts = { "8101/tcp" = {}; };
          WorkingDir = "/app";
          Env = [
            "PORT=8101"
            "CLAUDE_MODEL=haiku"
            "HOME=/root"
            "SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "NIX_SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "FONTCONFIG_FILE=${fontConfig}"
            "PYTHONPATH=/app"
            "LD_LIBRARY_PATH=${ldLibraryPath}"
            # Tell Playwright where to find Chromium (PLAYWRIGHT_BROWSERS_PATH for auto-discovery)
            "PLAYWRIGHT_BROWSERS_PATH=${linuxPkgs.playwright-driver.browsers-chromium}"
            # Direct path to chrome binary (used by brochure_pdf.py / photo_search_pdf.py)
            "CHROMIUM_EXECUTABLE_PATH=${linuxPkgs.playwright-driver.browsers-chromium}/chrome-linux64/chrome"
          ];
        };
      };

      packages.x86_64-linux.default = self.packages.x86_64-linux.dockerImage;

      # Also expose for darwin hosts building linux images via remote builder
      packages.x86_64-darwin.dockerImage = self.packages.x86_64-linux.dockerImage;
      packages.x86_64-darwin.default = self.packages.x86_64-linux.dockerImage;

    } // flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfreePredicate = pkg:
            builtins.elem (lib.getName pkg) [ "claude-code" ];
        };
        p2nixDev = poetry2nix.lib.mkPoetry2Nix { inherit pkgs; };
      in {
        # Development shell — native to whatever system you're on
        devShells.default = pkgs.mkShell {
          buildInputs = [
            (p2nixDev.mkPoetryEnv {
              projectDir = self;
              python = pkgs.python312;
              preferWheels = true;
            })
            pkgs.claude-code
          ];
          shellHook = ''
            echo "RRG Brochure dev shell"
            echo "Run: python server.py"
          '';
        };
      }
    );
}
