using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using GLTFast;
using GLTFast.Materials;
using UnityEngine;
using UnityEngine.InputSystem;

namespace RFC.Horror
{
    [DefaultExecutionOrder(-1000)]
    public sealed class RfcBootstrap : MonoBehaviour
    {
        readonly List<GltfImport> imports = new List<GltfImport>();
        readonly List<Renderer> renderers = new List<Renderer>();
        readonly HashSet<string> visualNames = new HashSet<string>();
        readonly CancellationTokenSource lifetime = new CancellationTokenSource();
        static RfcBootstrap instance;
        RfcFirstPerson player;
        RfcVisibility visibility;
        RfcLighting lighting;
        Camera loadingCamera;
        Material roofMaterial;
        string status = "Подготовка карты…";
        string error;
        bool ready;
        bool showHelp = true;
        int colliderCount;
        float frameTime;
        float progress;
        GUIStyle titleStyle;
        GUIStyle textStyle;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatic() { instance = null; }

        void Awake()
        {
            if (instance != null && instance != this) { Destroy(gameObject); return; }
            instance = this;
            Application.targetFrameRate = 60;
            QualitySettings.vSyncCount = 0;
            QualitySettings.pixelLightCount = 4;
            QualitySettings.shadows = ShadowQuality.Disable;
            var go = new GameObject("Loading camera");
            go.transform.SetParent(transform, false);
            loadingCamera = go.AddComponent<Camera>();
            loadingCamera.clearFlags = CameraClearFlags.SolidColor;
            loadingCamera.backgroundColor = new Color(.035f, .05f, .07f);
            loadingCamera.cullingMask = 0;
        }

        async void Start()
        {
            if (instance != this) return;
            var ct = lifetime.Token;
            try
            {
                string folder = Path.Combine(Application.streamingAssetsPath, "RFC");
                var settings = JsonUtility.FromJson<WalkSettings>(await ReadText(Path.Combine(folder, "walk_settings.json"), ct));
                ct.ThrowIfCancellationRequested();
                if (settings == null || settings.spawnBlender == null || settings.spawnBlender.Length != 3)
                    throw new InvalidDataException("Некорректный walk_settings.json");
                for (int block = 1; block <= 3; block++)
                {
                    status = $"Загрузка блока {block}/3 — модели и текстуры…";
                    var parent = new GameObject($"Block_{block:00}_Visual");
                    parent.transform.SetParent(transform, false);
                    // glTFast flips X. Blender->glTF is (x,z,-y). This root rotation
                    // makes final Unity world (x,z,y), matching collider metadata.
                    parent.transform.localRotation = Quaternion.Euler(0f, 180f, 0f);
                    var import = new GltfImport(materialGenerator: new BuiltInMaterialGenerator());
                    imports.Add(import);
                    var path = new Uri(Path.GetFullPath(Path.Combine(folder, $"Block_{block:00}.glb.bytes"))).AbsoluteUri;
                    bool loaded = await import.Load(path, new ImportSettings
                    {
                        GenerateMipMaps = true,
                        AnisotropicFilterLevel = 4,
                        NodeNameMethod = NameImportMethod.Original,
                        TexturesReadable = false
                    }, ct);
                    ct.ThrowIfCancellationRequested();
                    if (!loaded) throw new InvalidDataException($"Не удалось загрузить Block_{block:00}.glb. Подробности в Console.");
                    if (!await import.InstantiateMainSceneAsync(parent.transform, ct))
                        throw new InvalidDataException($"Не удалось создать геометрию блока {block}.");
                    ct.ThrowIfCancellationRequested();
                    renderers.AddRange(parent.GetComponentsInChildren<Renderer>(true));
                    ValidateAnchor(parent.transform, $"B{block:00}-GROUND", block);
                    progress = block * .23f;
                }
                // Alpha cutout gives grating holes a depth buffer and avoids the
                // ordering problems of large stacked alpha-blended floor plates.
                var materials = new HashSet<Material>();
                foreach (var renderer in renderers)
                    foreach (var material in renderer.sharedMaterials)
                        if (material && materials.Add(material))
                        {
                            material.enableInstancing = true;
                            if (material.name.IndexOf("wall", StringComparison.OrdinalIgnoreCase) >= 0) roofMaterial = material;
                            if (material.name.IndexOf("grating", StringComparison.OrdinalIgnoreCase) >= 0)
                                BuiltInMaterialGenerator.SetAlphaModeMask(material, .5f);
                        }
                status = "Создание коллайдеров полов, стен и лестниц…";
                var envelope = JsonUtility.FromJson<RfcEnvelope<ColliderRecord[]>>(
                    await ReadText(Path.Combine(folder, "collision_proxies.json"), ct));
                if (envelope == null || envelope.data == null || envelope.data.Length == 0)
                    throw new InvalidDataException("В collision_proxies.json нет данных.");
                await AddColliders(envelope.data, ct);
                var lights = JsonUtility.FromJson<RfcEnvelope<LightRecord[]>>(
                    await ReadText(Path.Combine(folder, "lighting_groups.json"), ct));
                ct.ThrowIfCancellationRequested();
                if (lights == null || lights.data == null) throw new InvalidDataException("Не удалось прочитать lighting_groups.json");
                Physics.SyncTransforms();
                var spawn = RfcCoordinates.Position(settings.spawnBlender);
                if (Physics.CheckCapsule(spawn + Vector3.up * .40f, spawn + Vector3.up * 1.45f,
                    .35f, ~0, QueryTriggerInteraction.Ignore))
                    throw new InvalidDataException("Стартовая точка пересекает препятствие. Проверьте коллайдеры и координаты.");
                CreatePlayer(spawn, settings);
                visibility = gameObject.AddComponent<RfcVisibility>();
                visibility.Initialize(player.transform, renderers, settings.renderDistance);
                lighting = gameObject.AddComponent<RfcLighting>();
                lighting.Initialize(player.transform, lights.data);
                Destroy(loadingCamera.gameObject);
                loadingCamera = null;
                ready = true;
                progress = 1f;
                status = "Карта загружена";
                Debug.Log($"RFC ready: {renderers.Count} renderers, {colliderCount} colliders. Click Game view to walk.");
            }
            catch (OperationCanceledException) { }
            catch (Exception exception)
            {
                if (this == null) return;
                error = exception.Message;
                status = "Загрузка остановлена";
                Cursor.lockState = CursorLockMode.None;
                Cursor.visible = true;
                Debug.LogException(exception, this);
            }
        }

        static Task<string> ReadText(string path, CancellationToken ct)
            => Task.Run(() => File.ReadAllText(path), ct);

        void ValidateAnchor(Transform root, string anchorName, int block)
        {
            Transform anchor = null;
            foreach (var node in root.GetComponentsInChildren<Transform>(true))
                { visualNames.Add(node.name); if (node.name == anchorName) anchor = node; }
            if (!anchor) throw new InvalidDataException("Не найден контрольный пол " + anchorName);
            Vector3 expected = block == 1 ? new Vector3(210f, -.12f, 160f)
                : block == 2 ? new Vector3(700f, -.12f, 180f) : new Vector3(1190f, -.12f, 160f);
            if (Vector3.Distance(anchor.position, expected) > .08f)
                throw new InvalidDataException("Ориентация GLB не совпадает с коллайдерами: " + anchorName);
        }

        async Task AddColliders(ColliderRecord[] records, CancellationToken ct)
        {
            var root = new GameObject("Static collision proxies");
            root.transform.SetParent(transform, false);
            for (int i = 0; i < records.Length; i++)
            {
                ct.ThrowIfCancellationRequested();
                var record = records[i];
                if (record.position_m == null || record.position_m.Length != 3 || record.size_m == null
                    || record.size_m.Length != 3 || record.rotation_euler_rad == null || record.rotation_euler_rad.Length != 3)
                    throw new InvalidDataException("Повреждённый коллайдер: " + record.id);
                var size = RfcCoordinates.Size(record.size_m);
                if (size.x <= 0 || size.y <= 0 || size.z <= 0)
                    throw new InvalidDataException("Нулевой габарит коллайдера: " + record.id);
                bool roof = record.id.EndsWith("-ROOF", StringComparison.Ordinal) && !visualNames.Contains(record.id);
                var go = roof ? GameObject.CreatePrimitive(PrimitiveType.Cube) : new GameObject(record.id);
                go.name = record.id;
                go.transform.SetParent(root.transform, false);
                go.transform.SetPositionAndRotation(RfcCoordinates.Position(record.position_m),
                    RfcCoordinates.Rotation(record.rotation_euler_rad));
                go.isStatic = true;
                var collider = roof ? go.GetComponent<BoxCollider>() : go.AddComponent<BoxCollider>();
                if (roof)
                {
                    // Hidden roof collections were absent from the visual GLBs.
                    // Reconstruct seven solid roof panels from the source proxies.
                    go.transform.localScale = size;
                    collider.size = Vector3.one;
                    var roofRenderer = go.GetComponent<MeshRenderer>();
                    if (roofMaterial) roofRenderer.sharedMaterial = roofMaterial;
                    renderers.Add(roofRenderer);
                }
                else collider.size = size;
                colliderCount++;
                if (i % 128 == 0)
                {
                    status = $"Коллайдеры: {i + 1:N0} / {records.Length:N0}";
                    progress = .69f + .28f * (i + 1f) / records.Length;
                    await Task.Yield();
                }
            }
        }

        void CreatePlayer(Vector3 spawn, WalkSettings settings)
        {
            var go = new GameObject("RFC Player");
            go.transform.SetParent(transform, false);
            go.transform.SetPositionAndRotation(spawn, Quaternion.Euler(0, 90, 0));
            go.AddComponent<CharacterController>();
            var cameraObject = new GameObject("Player camera");
            cameraObject.transform.SetParent(go.transform, false);
            cameraObject.transform.localPosition = new Vector3(0, 1.65f, 0);
            var camera = cameraObject.AddComponent<Camera>();
            camera.tag = "MainCamera";
            camera.fieldOfView = 75;
            camera.nearClipPlane = .05f;
            camera.farClipPlane = 250;
            camera.backgroundColor = new Color(.12f, .16f, .20f);
            camera.clearFlags = CameraClearFlags.SolidColor;
            cameraObject.AddComponent<AudioListener>();
            var lamp = new GameObject("Flashlight");
            lamp.transform.SetParent(cameraObject.transform, false);
            lamp.transform.localPosition = new Vector3(.12f, -.1f, .15f);
            var light = lamp.AddComponent<Light>();
            light.type = LightType.Spot;
            light.spotAngle = 65f;
            light.innerSpotAngle = 35f;
            light.range = 32f;
            light.intensity = 3f;
            light.color = new Color(.88f, .94f, 1f);
            light.shadows = LightShadows.None;
            player = go.AddComponent<RfcFirstPerson>();
            player.view = camera;
            player.flashlight = light;
            player.Initialize(settings);
        }

        void Update()
        {
            frameTime = Mathf.Lerp(frameTime, Time.unscaledDeltaTime, .08f);
            if (!ready || Keyboard.current == null) return;
            if (Keyboard.current.hKey.wasPressedThisFrame) showHelp = !showHelp;
            if (Keyboard.current.f5Key.wasPressedThisFrame && visibility) visibility.Toggle();
        }

        void OnGUI()
        {
            if (titleStyle == null)
            {
                titleStyle = new GUIStyle(GUI.skin.label) { fontSize = 24, fontStyle = FontStyle.Bold, wordWrap = true };
                titleStyle.normal.textColor = Color.white;
                textStyle = new GUIStyle(GUI.skin.label) { fontSize = 15, wordWrap = true };
                textStyle.normal.textColor = new Color(.82f, .88f, .93f);
            }
            if (!ready)
            {
                GUI.Box(new Rect(0, 0, Screen.width, Screen.height), GUIContent.none);
                float width = Mathf.Min(680f, Screen.width - 36f);
                var area = new Rect((Screen.width - width) / 2f, Screen.height * .30f, width, 250f);
                GUILayout.BeginArea(area);
                GUILayout.Label("RFC HORROR / UNITY", titleStyle);
                GUILayout.Space(16);
                GUILayout.Label(status, textStyle);
                if (error != null) GUILayout.Label(error + "\nПодробности: Window → General → Console.", textStyle);
                else
                {
                    GUILayout.Label("Первый запуск обрабатывает три GLB и текстуры. Дождись завершения.", textStyle);
                    var rect = GUILayoutUtility.GetRect(width - 20, 10);
                    GUI.Box(rect, GUIContent.none);
                    GUI.Box(new Rect(rect.x, rect.y, rect.width * progress, rect.height), GUIContent.none);
                }
                GUILayout.EndArea();
                return;
            }
            if (showHelp)
            {
                GUI.Box(new Rect(14, 14, Mathf.Min(535, Screen.width - 28), 178), GUIContent.none);
                GUILayout.BeginArea(new Rect(26, 22, Mathf.Min(510, Screen.width - 52), 164));
                GUILayout.Label("RFC HORROR / " + (lighting && lighting.Night ? "НОЧЬ" : "ДЕНЬ"), titleStyle);
                GUILayout.Label("WASD — ходьба · мышь — обзор · Shift — бег\nSpace — прыжок · F — фонарь · N — день/ночь\nEsc — курсор · клик в Game — вернуть управление\nH — подсказки · F5 — отсечение объектов · Ctrl+R — восстановление", textStyle);
                if (frameTime > 0) GUILayout.Label($"{1f / frameTime:F0} FPS · {colliderCount:N0} коллайдеров", textStyle);
                GUILayout.EndArea();
            }
            GUI.Label(new Rect(Screen.width / 2f - 6f, Screen.height / 2f - 12f, 20, 24), "+", textStyle);
        }

        void OnDestroy()
        {
            if (instance != this) return;
            lifetime.Cancel();
            foreach (var import in imports) import.Dispose();
            lifetime.Dispose();
            instance = null;
            Cursor.lockState = CursorLockMode.None;
            Cursor.visible = true;
        }
    }
}
