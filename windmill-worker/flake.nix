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

      # Pin the stock Windmill image (v1.627.0)
      windmillBase = pkgs.dockerTools.pullImage {
        imageName = "ghcr.io/windmill-labs/windmill";
        imageDigest = "sha256:6594f2ae765a5c49ee74490e6bdbd9d55f0ef1c83ddec570c3c51bf5bea7d281";
        sha256 = "";  # discover on first build
        finalImageTag = "main";
      };

      # Symlink claude into /usr/local/bin (already in stock image PATH)
      claudeLink = pkgs.runCommand "claude-in-path" {} ''
        mkdir -p $out/usr/local/bin
        ln -s ${pkgs.claude-code}/bin/claude $out/usr/local/bin/claude
      '';

    in {
      packages.${system} = rec {
        dockerImage = pkgs.dockerTools.buildLayeredImage {
          name = "windmill-worker";
          tag = "latest";
          fromImage = windmillBase;
          contents = [
            pkgs.claude-code
            pkgs.cacert
            claudeLink
          ];
        };

        default = dockerImage;
      };
    };
}
