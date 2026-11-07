# Auto-encuadre

El clip 9:16 se centra en quien habla. Se muestrea **1 frame por segundo**, se detectan rostros,
se suaviza la trayectoria con media móvil y se reduce a keyframes con zona muerta (la cámara
virtual no tiembla). FFmpeg recibe una expresión `crop=...:x='if(lt(t,..),..)'` con interpolación lineal.

## Layouts

| Situación | Layout |
|-----------|--------|
| Un hablante detectado en ≥ 35 % de las muestras | `crop`: recorte 9:16 dinámico centrado en el rostro |
| Dos rostros separados (> 25 % del ancho) en ≥ 35 % de las muestras | `split`: pantalla dividida, hablante izquierdo arriba y derecho abajo (solo 9:16) |
| Sin rostro fiable, o fuente ya vertical | `blur`: video completo sobre fondo desenfocado (layout original) |

El layout elegido se registra en el log (`Encuadre de <clip>: crop|split|blur`).

## Detector de rostros

OpenCV 5 ya no incluye los *Haar cascades*, por lo que el detector necesita el modelo
**YuNet** (ONNX, ~230 KB). Sin modelo ni Haar, el sistema funciona igual pero siempre usa `blur`.

Colócalo en `data/models/face_detection_yunet_2023mar.onnx`:

```powershell
New-Item -ItemType Directory -Force data\models
curl.exe -L -o data\models\face_detection_yunet_2023mar.onnx https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
```

Orden de backends: YuNet → Haar (solo OpenCV 4.x) → ninguno.

## Configuración

- `CLIP_SMART_FRAMING=0` desactiva el auto-encuadre (siempre `blur`).
- Constantes de umbrales en `src/agents/agent3_clip_generator/framing.py`.
