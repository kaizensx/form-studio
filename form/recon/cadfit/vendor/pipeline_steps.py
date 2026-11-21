# CADFit (https://github.com/ghadinehme/CADFit, commit 227a7acdc6972c646859d7e12da279e6e4ae2789), by Ghadi Nehme, Eamon Whalen and Faez Ahmed.
# Licensed CC BY-NC 4.0 (../LICENSE); included and modified in Form Studio with the author's permission (../PERMISSION.md).
# Modified for Form Studio: an excerpt of run_pipeline.py: _drop_nested_entries (step 4b), compute_mesh_volume, watertight,
# compute_difference_mesh and combine_cadquery_scripts (the residual refinement), unchanged but for their imports
# (shapely optional through _compat, normalize_mesh from .iou). run_pipeline.py's subprocess orchestration and its
# fillet/chamfer pass are not included: Form Studio's in-process driver is ../driver.py.
"""Steps of CADFit's pipeline (run_pipeline.py) the in-process driver needs: step 4b (drop sketch entries nested in
another on the same plane) and the helpers of the residual cut/union refinement."""
import numpy as np
import trimesh

from .iou import normalize_mesh


def _drop_nested_entries(entries, plane_dist_tol=1e-3, contain_frac=0.9):
    """Drop entries whose outer loop is contained in another entry's outer loop
    on the same plane. An entry's "outer loop" is the largest-area loop in
    `loops_3d`. Two entries are co-planar iff their normals are parallel (or
    anti-parallel) and the origin offset is perpendicular to that normal
    within `plane_dist_tol`.
    """
    if len(entries) < 2:
        return entries
    try:
        from .._compat import Polygon  # Modified for Form Studio: shapely optional
    except ImportError:
        return entries

    outers_world = []
    outer_areas = []
    origins = []
    normals = []
    for e in entries:
        loops = e.get('loops_3d') or []
        if not loops:
            outers_world.append(None); outer_areas.append(0); origins.append(None); normals.append(None)
            continue
        areas = e.get('loop_areas') or []
        if areas and len(areas) == len(loops):
            i_outer = int(np.argmax(areas))
        else:
            i_outer = max(range(len(loops)), key=lambda i: len(loops[i]))
        loop = np.array(loops[i_outer], dtype=float)
        if loop.shape[0] > 2 and np.allclose(loop[0], loop[-1]):
            loop = loop[:-1]
        outers_world.append(loop)
        outer_areas.append(float(areas[i_outer]) if areas and len(areas) == len(loops) else 0.0)
        origins.append(np.array(e.get('origin', [0, 0, 0]), dtype=float))
        normals.append(np.array(e.get('normal', [0, 0, 1]), dtype=float))

    keep = [True] * len(entries)
    n = len(entries)
    for i in range(n):
        if outers_world[i] is None or not keep[i]:
            continue
        ni = normals[i]
        ni_n = ni / (np.linalg.norm(ni) + 1e-12)
        # Build a 2D basis on plane i
        if abs(ni_n[2]) < 0.9:
            u = np.cross(ni_n, [0, 0, 1.0])
        else:
            u = np.cross(ni_n, [1.0, 0, 0])
        u = u / (np.linalg.norm(u) + 1e-12)
        v = np.cross(ni_n, u)
        oi = origins[i]
        try:
            poly_i = Polygon((outers_world[i] - oi) @ np.column_stack([u, v]))
            if not poly_i.is_valid:
                poly_i = poly_i.buffer(0)
            if poly_i.is_empty or poly_i.area <= 0:
                continue
        except Exception:
            continue
        for j in range(n):
            if i == j or not keep[j] or outers_world[j] is None:
                continue
            # Co-planarity check
            nj = normals[j]; nj_n = nj / (np.linalg.norm(nj) + 1e-12)
            if abs(abs(np.dot(ni_n, nj_n)) - 1.0) > 1e-3:
                continue
            if abs(np.dot(origins[j] - oi, ni_n)) > plane_dist_tol:
                continue
            # Smaller-area only — keep the bigger one
            if outer_areas[j] >= outer_areas[i] - 1e-9:
                continue
            pts_j_local = (outers_world[j] - oi) @ np.column_stack([u, v])
            try:
                poly_j = Polygon(pts_j_local)
                if not poly_j.is_valid:
                    poly_j = poly_j.buffer(0)
                if poly_j.is_empty:
                    continue
                inter = poly_j.intersection(poly_i).area
                if inter / max(poly_j.area, 1e-12) >= contain_frac:
                    keep[j] = False
            except Exception:
                continue
    return [e for k, e in zip(keep, entries) if k]


def compute_mesh_volume(mesh, normalize=False):
    """Compute volume of a mesh"""
    try:
        if isinstance(mesh, str):
            mesh = trimesh.load(mesh, force='mesh')
        if normalize:
            mesh = normalize_mesh(mesh)
        return abs(mesh.volume)
    except Exception as e:
        print(f"Warning: Could not compute volume: {e}")
        return 0.0

def watertight(mesh, stl_path):
    if not mesh.is_watertight:
        print(f"⚠️  Mesh is not watertight, applying cleanup...")
        try:
            import pymeshlab
            
            # Create temporary path for cleaned mesh
            temp_cleaned_path = stl_path + ".tmp_cleaned.stl"
            
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(stl_path)
            
            ms.meshing_remove_duplicate_vertices()
            ms.meshing_remove_duplicate_faces()
            ms.meshing_remove_unreferenced_vertices()
            ms.meshing_remove_null_faces()
            
            # Save cleaned mesh
            ms.save_current_mesh(temp_cleaned_path)
            
            # Replace original with cleaned version
            import shutil
            shutil.move(temp_cleaned_path, stl_path)
            
            # Reload to verify
            mesh = trimesh.load(stl_path, force='mesh')
            if mesh.is_watertight:
                print(f"✓ Mesh repaired and is now watertight")
            else:
                print(f"⚠️  Mesh still not watertight after cleanup")
        except ImportError:
            print(f"⚠️  pymeshlab not available for mesh repair")
        except Exception as e:
            print(f"⚠️  Mesh repair failed: {e}")
    else:
        print(f"✓ Mesh is watertight")
    return mesh
    

def compute_difference_mesh(mesh_a_path, mesh_b_path, output_path, normalize_a=False, normalize_b=False):
    """Compute difference A - B of two meshes and remove surface-like components"""
    try:
        mesh_a = trimesh.load(mesh_a_path, force='mesh')
        mesh_b = trimesh.load(mesh_b_path, force='mesh')

        if normalize_a:
            mesh_a = normalize_mesh(mesh_a)
        if normalize_b:
            mesh_b = normalize_mesh(mesh_b)

        mesh_a = watertight(mesh_a, stl_path=mesh_a_path)
        mesh_b = watertight(mesh_b, stl_path=mesh_b_path)
        
        # Compute difference (A - B)
        difference = mesh_a.difference(mesh_b)
        
        if difference is not None and hasattr(difference, 'export'):
            # Filter out surface-like components
            if hasattr(difference, 'split'):
                components = difference.split()
                volume_components = [c for c in components if abs(c.volume) > 0.01]
                
                if volume_components:
                    if len(volume_components) == 1:
                        difference = volume_components[0]
                    else:
                        difference = trimesh.util.concatenate(volume_components)
            
            difference.export(output_path)
            return True
        return False
    except Exception as e:
        print(f"Error computing difference: {e}")
        return False


def combine_cadquery_scripts(base_script_path, operation_script_path, output_script_path, operation='cut'):
    """
    Combine two CadQuery scripts using cut or union operation.
    
    Args:
        base_script_path: Path to the base CadQuery script (solid_n)
        operation_script_path: Path to the operation CadQuery script (solid_m)
        output_script_path: Path to save the combined script
        operation: 'cut' for solid_n.cut(solid_m) or 'union' for solid_n.union(solid_m)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Read both scripts
        with open(base_script_path, 'r') as f:
            base_lines = f.readlines()
        
        with open(operation_script_path, 'r') as f:
            operation_lines = f.readlines()
        
        # Process base script - extract body and find result variable
        base_body = []
        base_result_var = "result"
        skip_imports = True
        
        for i, line in enumerate(base_lines):
            # Skip imports at the beginning
            if skip_imports and (line.strip().startswith('import ') or line.strip() == ''):
                if line.strip() != '' or i < 3:  # Skip first few lines including imports
                    continue
                else:
                    skip_imports = False
                    continue
            
            # Stop at export or print statements
            if '.exportStl' in line or line.strip().startswith('print('):
                break
            
            # Track the last result variable assignment
            if ' = ' in line and '.val().exportStl' not in line:
                stripped = line.strip()
                if stripped.startswith('final_result'):
                    base_result_var = stripped.split('=')[0].strip()
                elif stripped.startswith('result'):
                    base_result_var = stripped.split('=')[0].strip()
            
            base_body.append(line)
        
        # Process operation script - extract body and find result variable
        operation_body = []
        operation_result_var = "result"
        skip_imports = True
        in_union_block = False
        
        for i, line in enumerate(operation_lines):
            # Skip imports at the beginning
            if skip_imports and (line.strip().startswith('import ') or line.strip() == ''):
                if line.strip() != '' or i < 3:
                    continue
                else:
                    skip_imports = False
                    continue
            
            # Stop at export or print statements
            if '.exportStl' in line or line.strip().startswith('print('):
                break
            
            # Skip comments about union/export
            if line.strip().startswith('#') and ('Union all solids' in line or 'Export' in line):
                in_union_block = True
                continue
            
            # Track the result variable
            if ' = ' in line and '.val().exportStl' not in line:
                stripped = line.strip()
                if stripped.startswith('result'):
                    operation_result_var = stripped.split('=')[0].strip()
            
            operation_body.append(line)
        
        # Rename variables in operation script to avoid conflicts
        operation_body_renamed = []
        
        for line in operation_body:
            renamed_line = line
            # Add _op suffix to main variables
            renamed_line = renamed_line.replace('solid_', 'solid_op_')
            renamed_line = renamed_line.replace('plane_', 'plane_op_')
            renamed_line = renamed_line.replace('sketch_', 'sketch_op_')
            
            # Fix result variable references more carefully
            if 'result_op_op' in renamed_line:
                renamed_line = renamed_line.replace('result_op_op', 'result_op')
            elif operation_result_var in renamed_line:
                # Use regex-like replacement to handle result variable properly
                import re
                # Replace 'result =' with 'result_op ='
                renamed_line = re.sub(r'\bresult\s*=', 'result_op =', renamed_line)
                # Replace 'result.union' or 'result.cut' with 'result_op.union' or 'result_op.cut'
                renamed_line = re.sub(r'\bresult\.', 'result_op.', renamed_line)
            
            operation_body_renamed.append(renamed_line)
        
        # Build combined script
        combined_lines = []
        
        # Add imports
        combined_lines.append("import cadquery as cq\n")
        combined_lines.append("import math\n")
        combined_lines.append("\n")
        
        # Add base script body
        combined_lines.extend(base_body)
        
        # Add result variable assignment if not already present
        if base_result_var == "result" and not any("result =" in line for line in base_body):
            # Find the last solid variable in base_body
            last_solid_var = None
            for line in reversed(base_body):
                if 'solid_' in line and ' = ' in line and '.extrude' in line:
                    last_solid_var = line.split('=')[0].strip()
                    break
            
            if last_solid_var:
                combined_lines.append(f"result = {last_solid_var}\n")
            elif base_body:
                # Look for result assignment that might have been excluded
                for line in base_lines:
                    if line.strip().startswith('result =') and '.exportStl' not in line:
                        combined_lines.append(line)
                        break
        
        # Add separator comment
        combined_lines.append("\n# ===== Operation Script =====\n")
        
        # Add operation script body
        combined_lines.extend(operation_body_renamed)
        
        # Add the cut/union operation
        combined_lines.append(f"\n# ===== Combine using {operation} =====\n")
        if operation == 'cut':
            combined_lines.append(f"final_result = {base_result_var}.cut(result_op)\n")
        else:  # union — use `.add()` (Compound) and let manifold3d clean it.
            combined_lines.append(f"final_result = {base_result_var}.add(result_op)\n")

        
        # Add export
        stl_output = output_script_path.replace('.py', '.stl')
        combined_lines.append(f"cq.exporters.export(final_result, '{stl_output}')\n")

        combined_lines.append(f"print('Successfully exported combined result to {stl_output}')\n")
        
        # Write combined script
        with open(output_script_path, 'w') as f:
            f.writelines(combined_lines)
        
        return True
        
    except Exception as e:
        print(f"Error combining CadQuery scripts: {e}")
        import traceback
        traceback.print_exc()
        return False
