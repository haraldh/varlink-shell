{
  description = "varlink-shell development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      devShells = forAllSystems (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.python314
              pkgs.uv
            ];

            shellHook = ''
              # Create a venv if it doesn't exist
              if [ ! -d .venv ]; then
                uv venv --python python3.14 .venv
                uv pip install varlink pytest pytest-cov ruff mypy
              fi
              source .venv/bin/activate
            '';
          };
        });
    };
}
