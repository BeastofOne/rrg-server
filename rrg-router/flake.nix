{
  description = "RRG Router — Streamlit chat UI with intent classification";

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

      # Python environment from poetry.lock (all deps pre-fetched, no network needed)
      pythonEnv = p2nix.mkPoetryEnv {
        projectDir = self;
        python = linuxPkgs.python312;
        preferWheels = true;
      };

      # Application source — all Python files
      appSrc = linuxPkgs.runCommand "rrg-router-src" {} ''
        mkdir -p $out/app
        cp ${./app.py} $out/app/app.py
        cp ${./graph.py} $out/app/graph.py
        cp ${./state.py} $out/app/state.py
        cp ${./config.py} $out/app/config.py
        cp ${./node_client.py} $out/app/node_client.py
        cp ${./windmill_client.py} $out/app/windmill_client.py
        cp ${./signal_client.py} $out/app/signal_client.py
        cp ${./claude_llm.py} $out/app/claude_llm.py
      '';

    in
    {
      # Docker image — always targets x86_64-linux
      packages.x86_64-linux.dockerImage = linuxPkgs.dockerTools.buildLayeredImage {
        name = "rrg-router";
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
          Cmd = [
            "${pythonEnv}/bin/streamlit" "run" "/app/app.py"
            "--server.port" "8501"
            "--server.address" "0.0.0.0"
            "--server.headless" "true"
            "--browser.gatherUsageStats" "false"
          ];
          ExposedPorts = { "8501/tcp" = {}; };
          WorkingDir = "/app";
          Env = [
            "CLAUDE_MODEL=haiku"
            "HOME=/root"
            "SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "NIX_SSL_CERT_FILE=${linuxPkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            "PYTHONPATH=/app"
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
            echo "RRG Router dev shell"
            echo "Run: streamlit run app.py"
          '';
        };
      }
    );
}
