{
  description = "RRG Commercial PA Microservice — conversational purchase agreement generator";

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

      # Python environment from poetry.lock
      # preferWheels = false avoids poetry2nix riscv64 wheel resolution bug
      # (lxml publishes riscv64 manylinux wheels that trigger missing arch in pep599.nix)
      pythonEnv = p2nix.mkPoetryEnv {
        projectDir = self;
        python = linuxPkgs.python312;
        preferWheels = false;
        overrides = p2nix.defaultPoetryOverrides.extend (final: prev: {
          lxml = prev.lxml.overridePythonAttrs (old: {
            nativeBuildInputs = (old.nativeBuildInputs or []) ++ [
              linuxPkgs.pkg-config
            ];
            buildInputs = (old.buildInputs or []) ++ [
              linuxPkgs.libxml2
              linuxPkgs.libxslt
            ];
          });
        });
      };

      # Application source — all Python files + templates
      appSrc = linuxPkgs.runCommand "rrg-commercial-pa-src" {} ''
        mkdir -p $out/app/templates
        cp ${./server.py} $out/app/server.py
        cp ${./graph.py} $out/app/graph.py
        cp ${./pa_handler.py} $out/app/pa_handler.py
        cp ${./pa_docx.py} $out/app/pa_docx.py
        cp ${./draft_store.py} $out/app/draft_store.py
        cp ${./claude_llm.py} $out/app/claude_llm.py
        cp ${./provisions.py} $out/app/provisions.py
        cp ${./templates/commercial_pa.docx} $out/app/templates/commercial_pa.docx
      '';

    in
    {
      # Docker image — always targets x86_64-linux
      packages.x86_64-linux.dockerImage = linuxPkgs.dockerTools.buildLayeredImage {
        name = "rrg-commercial-pa";
        tag = "latest";

        contents = [
          pythonEnv
          linuxPkgs.claude-code
          linuxPkgs.coreutils
          linuxPkgs.bashInteractive
          linuxPkgs.cacert
          appSrc
        ];

        config = {
          Cmd = [ "${pythonEnv}/bin/python" "/app/server.py" ];
          ExposedPorts = { "8102/tcp" = {}; };
          WorkingDir = "/app";
          Env = [
            "PORT=8102"
            "CLAUDE_MODEL=haiku"
            "HOME=/root"
            "SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "NIX_SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "PYTHONPATH=/app"
            "PA_DB_PATH=/data/pa_drafts.db"
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
            echo "RRG Commercial PA dev shell"
            echo "Run: python server.py"
          '';
        };
      }
    );
}
