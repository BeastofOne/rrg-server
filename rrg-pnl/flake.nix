{
  description = "RRG P&L Microservice — persistent Flask container with LangGraph + WeasyPrint";

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

      # WeasyPrint runtime system libraries
      weasyPrintDeps = with linuxPkgs; [
        pango
        cairo
        gdk-pixbuf
        glib
        harfbuzz
        fontconfig
        freetype
        libffi
        zlib
      ];

      # Python environment from poetry.lock (all deps pre-fetched, no network needed)
      pythonEnv = p2nix.mkPoetryEnv {
        projectDir = self;
        python = linuxPkgs.python312;
        preferWheels = true;
        overrides = p2nix.overrides.withDefaults (final: prev: {
          weasyprint = prev.weasyprint.overridePythonAttrs (old: {
            buildInputs = (old.buildInputs or []) ++ weasyPrintDeps;
            patches = [];
            patchPhase = "true";  # Skip patching entirely — LD_LIBRARY_PATH handles lib loading
          });
        });
      };

      # Application source — all Python files + templates
      appSrc = linuxPkgs.runCommand "rrg-pnl-src" {} ''
        mkdir -p $out/app/templates
        cp ${./server.py} $out/app/server.py
        cp ${./graph.py} $out/app/graph.py
        cp ${./pnl_handler.py} $out/app/pnl_handler.py
        cp ${./pnl_pdf.py} $out/app/pnl_pdf.py
        cp ${./claude_llm.py} $out/app/claude_llm.py
        cp ${./templates/pnl.html} $out/app/templates/pnl.html
      '';

      # WeasyPrint needs fonts at runtime
      fontConfig = linuxPkgs.makeFontsConf {
        fontDirectories = [
          linuxPkgs.liberation_ttf
          linuxPkgs.noto-fonts
        ];
      };

      # Build LD_LIBRARY_PATH for WeasyPrint's ctypes.find_library
      ldLibraryPath = lib.makeLibraryPath weasyPrintDeps;

    in
    {
      # Docker image — always targets x86_64-linux
      packages.x86_64-linux.dockerImage = linuxPkgs.dockerTools.buildLayeredImage {
        name = "rrg-pnl";
        tag = "latest";

        contents = [
          pythonEnv
          linuxPkgs.claude-code
          linuxPkgs.coreutils
          linuxPkgs.bashInteractive
          linuxPkgs.cacert
          linuxPkgs.liberation_ttf
          linuxPkgs.noto-fonts
          appSrc
        ] ++ weasyPrintDeps;

        config = {
          Cmd = [ "${pythonEnv}/bin/python" "/app/server.py" ];
          ExposedPorts = { "8100/tcp" = {}; };
          WorkingDir = "/app";
          Env = [
            "PORT=8100"
            "CLAUDE_MODEL=haiku"
            "HOME=/root"
            "SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "NIX_SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "FONTCONFIG_FILE=${fontConfig}"
            "PYTHONPATH=/app"
            "LD_LIBRARY_PATH=${ldLibraryPath}"
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
            echo "RRG P&L dev shell"
            echo "Run: python server.py"
          '';
        };
      }
    );
}
