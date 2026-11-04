{
  description = "Sovngarde font — glyph coverage extension (desktop TTF + Skyrim Scaleform SWF)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      eachSystem = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));
    in
    {
      devShells = eachSystem (
        pkgs:
        let
          python = pkgs.python3.withPackages (ps: [
            ps.fonttools
            ps.pillow
            ps.ruff
            ps.mypy
            ps.pytest
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.fontforge
              pkgs.unzip
              pkgs.p7zip
              pkgs.jq
            ];
            # src layout: run the package straight from the tree
            PYTHONPATH = "src";
          };
        }
      );
    };
}
