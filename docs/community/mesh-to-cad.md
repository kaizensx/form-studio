# Mesh to editable CAD

Bring an STL, OBJ or 3MF and Form Studio rebuilds it as CAD, then measures how close the result is to the mesh. This guide explains the two routes (the automatic **Make editable** and a rebuild by your agent), how to read the report, and what it cannot do yet.

Mesh to CAD is new in version 1.1 (in the Preview channel first). Analytic and freeform faces and the feature tree are Beta.

## Start

- **In the app:** import the mesh (drop it on Home or attach it to a conversation), then press **Make editable** next to it in Describe › Reference parts.
- **From a terminal:** `form reconstruct FILE [--name N] [--tolerance MM] [--layer 0|1|2]`
- **From an agent:** the MCP tool `reconstruct`.

The result is a new design. The original mesh stays beside it as a blueprint reference, and the report, the deviation map and every solid are kept in the design's `reconstruction` folder.

Several meshes of one product become **one design with one part per mesh**, in the positions the files give:

```bash
form reconstruct base.stl lid.stl hinge.stl
```

Each part keeps its own parameters, named after the part (`base__fillet1_r`). A part that cannot be reconstructed is reported and the others are kept.

## How to read the result

Every result leads with **editable**: the share of its surface that its parameters make (sketches, extrusions, holes, fillets). Then comes its distance to the mesh (the two-sided Hausdorff distance) and whether that is within the tolerance you asked for.

- A design is titled **(editable)** from 50 %, **(partly editable)** below that and **(exact copy)** at 0 %.
- A result outside the tolerance is still offered when it is the best verified one, and says so.
- The report also gives the volume difference, the share of area that is parametric, freeform and frozen, and a deviation map coloured against the tolerance.

A solid can be all analytic surfaces and still not be editable. The editable share is the number to look at.

## What it tries, in order

**Sketches and extrusions first (Beta).** The part is read the way it was modelled. Along its main direction it is cut at every height a mesh vertex sits at. Each section's loops become sketches of lines, arcs and rounded corners. A loop that does not change between two levels becomes an extrusion; one that changes linearly (a chamfer, a draft) becomes a ruled loft between two sketches. Values within a quarter of the tolerance become one parameter, snapped to a round number when that is within reach, and diameters are snapped to standard hole sizes. Holes and pockets are cuts, bosses and steps are additions. What does not read as a sketch (a rounded top, a freeform band) is kept as the mesh's own slices and booleaned in, so the rest stays parametric.

**Layer 0: the mesh as an exact solid.** Vertices are welded, every triangle becomes a planar face, the faces are sewn into a solid and coplanar facets are merged. The distance to the mesh is at float precision. Open boundaries and non-manifold edges are reported. This layer always works.

**Layer 1 (Beta): analytic and freeform faces.** Regions are grown over the mesh and fitted with planes, cylinders, cones, spheres and tori. A region is accepted only when every vertex on it is within the tolerance (0.02 mm by default). Smooth regions that no simple surface explains are fitted with bicubic B-spline patches and reported as "freeform (B-spline fitted)".

**Layer 2 (Beta): a feature tree.** Holes (plain, counterbored, countersunk, blind or through), constant-radius fillets and equal-distance chamfers are found and taken off the solid. What is left becomes an extrusion stack, a revolution or, when it is neither, the reconstructed solid kept exactly under parametric features. The features go back on as real operations: holes snapped to standard sizes, holes on a grid, a line or a circle as one pattern. A spur gear is recognised from its outline and becomes a parametric gear.

When the first route verifies with most of the surface editable, it is the result in seconds. Otherwise the layers run, and the verified result with the most editable surface wins. A feature that does not verify is left in the base and named in the report.

## The other route: your agent rebuilds it

For a part that should read like it was designed from scratch (named features, parameters for the dimensions that matter, edges only where the part has edges), let the agent rebuild it. **Rebuild as editable CAD** in Describe › Reference parts starts it. The mesh stays in the design as a blueprint reference and is never used as the design itself.

1. **Read the mesh.** `analyze_reference` cuts sections in the three principal planes and returns them as pictures with dimensions and as vector outlines. It lists holes and bosses, pockets and slots, plates, walls and ribs, steps, ramps, draft, fillets, chamfers, symmetry and wall thicknesses, each with its sizes.
2. **Understand how parts move.** For several meshes, `analyze_assembly` reports mating surfaces, the smallest clearance per pair, how far each part can slide or turn against the fixed one, and names the joints. Parts are rigid; springs and gravity are not simulated.
3. **Build it** as build123d code with parameters.
4. **Check the rebuild.** `compare_to_reference` measures the design against the mesh: two-sided Hausdorff, mean and 99th percentile, a picture coloured by deviation, the worst regions in words and coordinates, and per feature the design's own diameter or radius next to the mesh's. The default limit for a remodel is 0.1 mm.
5. **Refine** until it is within the limit.

The staged workflow for agents is `design_guide(topic="reference_parts")`.

## Optional engines

Two optional engines add one more candidate each. Mesh to CAD works fully without them, and every proposal is snapped to the mesh and kept only when it verifies.

- **CAD-Recode:** a learned model that reads a mesh as a point cloud and writes a sketch-and-extrude program. Worth it for simple, boxy parts. Non-commercial use only.
- **CADFit:** a search that tries extrusions and revolves against the mesh. Slower than the built-in route; worth it when a part made of extruded and turned shapes does not come out right. Non-commercial use only.

Sizes, licences and how to install them are in the guide **Optional engines**.

## What it does not do yet

- A part whose surfaces curve across every axis (a casting, a scan, a rounded top) keeps those regions as the mesh's own slices: exact, but not editable.
- The sketches route reads one main direction plus the three axes, not tilted ones.
- Fillets of varying radius, fillets whose sharp edge cannot be rebuilt and holes that cannot be taken off the solid stay in the base and are listed.
- Gears: spur gears only (no helical, bevel or internal gears).
- Accuracy is measured against the mesh, not the original object. A mesh's own chord error and scan noise are in the input.
- Units are millimetres unless the file says otherwise (3MF does).
- Nothing is decimated. A mesh over 200,000 triangles shows progress and takes minutes.

## Tips

- Export the mesh as finely as you can. A coarse mesh of a curved surface can be farther from any smooth surface than the tolerance.
- If the tolerance is too strict for your mesh, raise it: `--tolerance 0.05`.
- Check the units first. An STL carries none, and Form Studio reads it as millimetres.
- Share results, reports and edge cases in #mesh-to-cad. For a problem, post in #help with the tag **Mesh to CAD**, the mesh if you may share it, and the report.

How it is measured across a set of parts: [the reconstruction bench](https://github.com/kaizensx/form-studio/blob/dev/docs/RECON_BENCH.md).
