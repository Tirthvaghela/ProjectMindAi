# Technology alias audit

194 distinct technology names; 41 are canonical names in `nlp/skills.py`, 153 are not. **Uncovered does not mean unmatched**: every name still matches itself case-, space- and punctuation-insensitively. An alias is only needed when two *different* spellings mean the same thing.

## Covered by the table
AWS, C#, C++, CSS, D3.js, Django, Docker, Express, FastAPI, Flask, Git, GitHub Actions, Go, JavaScript, Keras, Kotlin, Kubernetes, Matplotlib, MongoDB, Next.js, Node.js, NumPy, OpenCV, Pandas, PostgreSQL, PyTorch, Python, Raspberry Pi, React, React Native, Redis, SQLite, SciPy, Sentence Transformers, Tailwind CSS, TensorFlow, TensorFlow Lite, Terraform, Transformers, TypeScript, scikit-learn

## Spellings the catalogue already writes two ways (unified by normalisation)
- pypdf: PyPDF, pypdf

## Near variants — candidates for a human decision, never mapped automatically
- `dnspython` ~ `Python` (one name contains the other, 0.8)
- `GeoPandas` ~ `Pandas` (one name contains the other, 0.8)
- `GitPython` ~ `Python` (one name contains the other, 0.8)
- `Python` ~ `python-chess` (one name contains the other, 0.71)
- `PyTorch` ~ `PyTorch Geometric` (one name contains the other, 0.61)
- `React` ~ `React Native` (one name contains the other, 0.62)
- `Sentence Transformers` ~ `Transformers` (one name contains the other, 0.75)
- `TensorFlow` ~ `TensorFlow Lite` (one name contains the other, 0.83)

## Ambiguous names (short, plain English, or a second reading)
Blender, C#, Dart, Expo, Express, Gazebo, Go, Hardhat, Leaflet, Prophet, S3, Surprise, Unity

## Alias collisions with a different catalogue technology (must be empty)
- none

## Uncovered names (project count)
Streamlit (93), MQTT (57), Plotly (56), Solidity (49), ESP32 (46), Unity (44), Hardhat (37), Flutter (36), Dart (35), ROS (34), Grafana (33), spaCy (33), Arduino (28), statsmodels (28), torchvision (28), Firebase (26), Blender (23), Ethereum (23), OpenXR (23), ARCore (20), Expo (18), Gazebo (18), InfluxDB (18), Seaborn (18), YOLOv8 (13), pytest (13), Prometheus (12), Librosa (11), MediaPipe (10), NetworkX (10), Pillow (10), Web3.js (10), Elasticsearch (9), IPFS (9), FAISS (8), GeoPandas (8), SHAP (8), NLTK (7), Chart.js (6), Gymnasium (6), OR-Tools (6), Scapy (6), Tesseract (6), Whisper (6), XGBoost (6), cryptography (5), OpenZeppelin (4), Playwright (4), hashlib (4), AWS Lambda (3), Cloud Firestore (3), Node-RED (3), OWASP (3), Prophet (3), PyYAML (3), Socket.IO (3), SpeechRecognition (3), Stable-Baselines3 (3), Vite (3), Android Sensors (2), BeautifulSoup (2), Bluetooth LE (2), GitPython (2), Graphviz (2), Jetpack Compose (2), Leaflet (2), Locust (2), MLflow (2), Markdown-it (2), PyBullet (2), Retrofit (2), SimPy (2), Surprise (2), Web Workers (2), WorkManager (2), Workbox (2), ethers.js (2), music21 (2), rasterio (2), scikit-image (2), Airflow (1), Apollo Server (1), CodeMirror (1), CycloneDX (1), DEAP (1), DVC (1), DiCE (1), DuckDB (1), Evidently (1), FMOD (1), Fairlearn (1), Fast Downward (1), Foundry (1), Gensim (1), GitHub API (1), GraphQL (1), HTML Canvas (1), Helm (1), IndexedDB (1), Jaeger (1), Kafka (1), LightGBM (1), Lighthouse (1), LoRa (1), MAPIE (1), MIDI (1), MJML (1), Mesa (1), MetaMask (1), Neo4j (1), Nmap (1), ONNX (1), Open Policy Agent (1), OpenTelemetry (1), Optuna (1), PDDL (1), PowerShell (1), PyJWT (1), PyPDF (1), PyTorch Geometric (1), Rasa (1), River (1), S3 (1), Slack API (1), Storybook (1), Stripe (1), SymPy (1), Web Components (1), WebAssembly (1), WebAuthn (1), androguard (1), bcrypt (1), circom (1), dateparser (1), dnspython (1), face_recognition (1), imagehash (1), imbalanced-learn (1), jellyfish (1), lifelines (1), mlxtend (1), pgmpy (1), pre-commit (1), psutil (1), py_trees (1), pypdf (1), python-chess (1), pyttsx3 (1), requests (1), scikit-fuzzy (1), snarkjs (1), sslyze (1), yfinance (1)
