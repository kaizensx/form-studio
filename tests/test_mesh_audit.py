import importlib.util
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'form' / 'mesh_audit.py'
spec = importlib.util.spec_from_file_location('mesh_audit', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def cube(size=20, offset=(0, 0, 0)):
    vertices = [(0,0,0),(size,0,0),(size,size,0),(0,size,0),
                (0,0,size),(size,0,size),(size,size,size),(0,size,size)]
    vertices = [tuple(a+b for a,b in zip(v,offset)) for v in vertices]
    faces = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
             (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    return [tuple(vertices[i] for i in f) for f in faces]

def write_binary(path, triangles):
    data = bytearray(b'solid binary fixture'.ljust(80,b'\0'))
    data.extend(struct.pack('<I',len(triangles)))
    for t in triangles:
        data.extend(struct.pack('<12fH',0,0,0,*(c for v in t for c in v),0))
    Path(path).write_bytes(data)

class AuditTests(unittest.TestCase):
    def test_cube_volume_dimensions(self):
        r=m.audit(cube(),expected_size=[20,20,20])
        self.assertEqual(r['status'],'PASS_LIMITED_SCREEN')
        self.assertAlmostEqual(r['signed_component_volumes_mm3'][0],8000)
    def test_translated_cube(self):
        r=m.audit(cube(offset=(-500,1000,-200)))
        self.assertEqual(r['status'],'PASS_LIMITED_SCREEN')
        self.assertAlmostEqual(r['signed_component_volumes_mm3'][0],8000)
    def test_missing_face(self):
        self.assertIn('open_boundary',m.audit(cube()[:-1])['failures'])
    def test_reversed_face(self):
        t=cube();t[0]=tuple(reversed(t[0]))
        self.assertIn('inconsistent_winding',m.audit(t)['failures'])
    def test_inward_shell(self):
        self.assertIn('nonpositive_component_volume',m.audit([tuple(reversed(t)) for t in cube()])['failures'])
    def test_duplicate(self):
        self.assertIn('duplicate_faces',m.audit(cube()+cube()[:1])['failures'])
    def test_zero_area(self):
        self.assertIn('degenerate_faces',m.audit(cube()+[((0,0,0),)*3])['failures'])
    def test_multiple_components(self):
        t=cube()+cube(offset=(30,0,0))
        self.assertIn('unexpected_component_count',m.audit(t)['failures'])
        self.assertEqual(m.audit(t,expected_components=2)['status'],'PASS_LIMITED_SCREEN')
    def test_nonfinite(self):
        t=cube();t[0]=((math.nan,0,0),t[0][1],t[0][2])
        self.assertIn('nonfinite_coordinates',m.audit(t)['failures'])
    def test_envelope(self):
        self.assertIn('exceeds_axis_aligned_envelope',m.audit(cube(175))['failures'])
    def test_dimensions(self):
        self.assertIn('unexpected_dimensions',m.audit(cube(),expected_size=[21,20,20])['failures'])
    def test_empty(self):
        self.assertIn('empty_mesh',m.audit([])['failures'])
    def test_invalid_settings(self):
        for kwargs in [{'weld_grid':0},{'margin':90},{'expected_components':0}, {'expected_size':[math.nan,20,20]}]:
            with self.assertRaises(ValueError):m.audit(cube(),**kwargs)
    def test_binary_roundtrip_and_cli(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cube.stl';write_binary(p,cube())
            t,fmt,_=m.read_stl(p)
            self.assertEqual(fmt,'binary');self.assertEqual(t,cube())
            result=subprocess.run([sys.executable,str(SCRIPT),str(p)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([sys.executable,str(SCRIPT),str(p),'--expect-size','30','30','30'],capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
    def test_ascii_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cube.stl'
            lines=['solid test']
            for t in cube():
                lines+=['facet normal 0 0 0','outer loop']
                lines+=['vertex '+' '.join(map(str,v)) for v in t]
                lines+=['endloop','endfacet']
            p.write_text('\n'.join(lines+['endsolid test']), encoding="utf-8")
            t,fmt,_=m.read_stl(p)
            self.assertEqual(fmt,'ascii');self.assertEqual(t,cube())
    def test_truncated_binary(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'bad.stl';write_binary(p,cube())
            p.write_bytes(p.read_bytes()[:-7])
            with self.assertRaises(ValueError):m.read_stl(p)

if __name__=='__main__':unittest.main()
