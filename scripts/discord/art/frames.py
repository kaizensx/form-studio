# Frames of art/banner.html for art/welcome.gif:  python art/frames.py art/banner.html OUTDIR 1600 900 15 17.5
import sys, time
from PySide6.QtCore import QUrl, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
src, outdir, w, h, fps, secs = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6])
app = QApplication([]); v = QWebEngineView(); v.resize(w // 2, h // 2); v.show()
v.loadFinished.connect(lambda ok: v.setZoomFactor(0.5))
v.load(QUrl.fromLocalFile(src))
t0 = [None]; n = [0]; ts = open(outdir + "/t.txt", "w")
def tick():
    if t0[0] is None: t0[0] = time.time()
    v.grab().save("%s/f%04d.png" % (outdir, n[0])); ts.write("%.3f\n" % (time.time() - t0[0])); n[0] += 1
    if time.time() - t0[0] > secs: ts.close(); app.quit()
tm = QTimer(); tm.timeout.connect(tick)
QTimer.singleShot(600, lambda: tm.start(int(1000 / fps)))
app.exec(); print(n[0], "frames")
