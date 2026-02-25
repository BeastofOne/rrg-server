{
  description = "Windmill Worker + Claude CLI";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      lib = nixpkgs.lib;
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfreePredicate = pkg:
          builtins.elem (lib.getName pkg) [ "claude-code" ];
      };

      # Pin the stock Windmill image
      windmillBase = pkgs.dockerTools.pullImage {
        imageName = "ghcr.io/windmill-labs/windmill";
        imageDigest = "sha256:6594f2ae765a5c49ee74490e6bdbd9d55f0ef1c83ddec570c3c51bf5bea7d281";
        sha256 = "";  # discover on first build
        finalImageTag = "main";
      };

      # Single layer: only a symlink at /usr/local/bin/claude.
      # claude-code + cacert Nix store paths are pulled in via the
      # closure (as /nix/store/* layers) — they do NOT create
      # root-level /bin, /lib, /etc dirs that would mask the base image.
      claudeLayer = pkgs.runCommand "claude-layer" {} ''
        mkdir -p $out/usr/local/bin
        ln -s ${pkgs.claude-code}/bin/claude $out/usr/local/bin/claude

        # SSL certs: create a Nix-specific cert file that won't mask
        # the base image's /etc/ssl/certs/ directory
        mkdir -p $out/etc/ssl/certs
        ln -s ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt $out/etc/ssl/certs/ca-bundle-nix.crt
      '';

    in {
      packages.${system} = rec {
        dockerImage = pkgs.dockerTools.buildLayeredImage {
          name = "windmill-worker";
          tag = "latest";
          fromImage = windmillBase;
          # ONLY include claudeLayer — NOT pkgs.claude-code or pkgs.cacert directly.
          # Including them directly creates root-level /bin, /lib symlinks in the
          # "customisation layer" that mask the base image's directories.
          contents = [ claudeLayer ];
        };

        default = dockerImage;
      };
    };
}
