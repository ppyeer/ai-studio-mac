"""Picture measurements of one take (OpenCV; the face detector needs OpenCV >= 4.5.4).

measure(path, cuts, yunet=None) -> {"fps", "dur", "scale": [[t, s|None], ...], "faces": [[t, face_h, yaw, pitch], ...]}
  scale  frame-to-frame similarity scale from ORB matches (> 1 = the picture grows, as in a push-in); None when it
         cannot be measured. Frames next to a cut are skipped.
  faces  the largest face at 4 fps from YuNet's 5 landmarks (only with a YuNet model file). face_h = face height /
         frame height. yaw = (nose x - eye midpoint x) / eye distance: |yaw| < 0.12 reads as looking into the lens.
         pitch = nose height between the eye line (0) and the mouth line (1); it drops when the head bows.
"""
import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")   # OpenCV 5 warns about DNN targets on every YuNet load
import cv2  # noqa: E402
import numpy as np  # noqa: E402

LONG_SIDE = 672


def frame_scale(bf, a, b):
    (k1, d1), (k2, d2) = a, b
    if d1 is None or d2 is None or len(k1) <= 30 or len(k2) <= 30:
        return None
    m = bf.match(d1, d2)
    if len(m) <= 30:
        return None
    p1 = np.float32([k1[x.queryIdx].pt for x in m])
    p2 = np.float32([k2[x.trainIdx].pt for x in m])
    M, inl = cv2.estimateAffinePartial2D(p1, p2, ransacReprojThreshold=2)
    if M is None or inl is None or inl.sum() <= 25:
        return None
    return float(np.hypot(M[0, 0], M[1, 0]))


def face(det, img, t, H):
    _, fs = det.detect(img)
    if fs is None or not len(fs):
        return [round(t, 3), 0.0, None, None]
    x = max(fs, key=lambda r: r[3])
    er, el, no, mr, ml = x[4:6], x[6:8], x[8:10], x[10:12], x[12:14]
    ed = float(np.hypot(*(el - er))) or 1.0
    ey, my = (er[1] + el[1]) / 2, (mr[1] + ml[1]) / 2
    pitch = float(no[1] - ey) / float(my - ey) if my - ey > 1 else None
    yaw = float(no[0] - (er[0] + el[0]) / 2) / ed
    return [round(t, 3), round(float(x[3]) / H, 3), round(yaw, 3), None if pitch is None else round(pitch, 3)]


def measure(path, cuts, yunet=None):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV cannot open {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    w0, h0 = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    k = LONG_SIDE / max(w0, h0, 1)
    W, H = int(round(w0 * k)), int(round(h0 * k))
    det = cv2.FaceDetectorYN.create(str(yunet), "", (W, H), 0.6, 0.3, 50) if yunet else None
    orb, bf = cv2.ORB_create(800), cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    prev, n, scale, faces, step = None, 0, [], [], max(1, round(fps / 4))
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = n / fps
        f = cv2.resize(f, (W, H))
        kd = orb.detectAndCompute(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), None)
        near_cut = any(abs(t - c) < 1.5 / fps for c in cuts)
        scale.append([round(t, 3), frame_scale(bf, prev, kd) if prev is not None and not near_cut else None])
        if det is not None and n % step == 0:
            faces.append(face(det, f, t, H))
        prev, n = kd, n + 1
    return {"fps": fps, "dur": n / fps, "scale": scale, "faces": faces}
