using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace RFC.Horror.Editor
{
    [InitializeOnLoad]
    public static class RfcEditorSetup
    {
        const string ScenePath = "Assets/RFC/Scenes/RFC_Walk.unity";
        static RfcEditorSetup() { EditorApplication.delayCall += FirstOpen; }

        static void FirstOpen()
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode) return;
            if (SessionState.GetBool("RFC.Setup.Done", false)) return;
            SessionState.SetBool("RFC.Setup.Done", true);
            EnsureBuildShaders();
            var active = SceneManager.GetActiveScene();
            if (string.IsNullOrEmpty(active.path) && !active.isDirty) OpenScene();
        }

        [MenuItem("RFC/Open Walk Scene")]
        public static void OpenScene()
        {
            if (EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
                EditorSceneManager.OpenScene(ScenePath);
        }

        // Runtime GLB materials need their shaders in standalone builds, too.
        [MenuItem("RFC/Include Runtime Shaders")]
        public static void EnsureBuildShaders()
        {
            var assets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/GraphicsSettings.asset");
            if (assets.Length == 0) return;
            var graphics = new SerializedObject(assets[0]);
            var array = graphics.FindProperty("m_AlwaysIncludedShaders");
            if (array == null || !array.isArray) return;
            foreach (var name in new[] { "glTF/PbrMetallicRoughness", "glTF/PbrSpecularGlossiness", "glTF/Unlit" })
            {
                var shader = Shader.Find(name);
                if (!shader) { Debug.LogWarning("RFC: shader not found yet: " + name); continue; }
                bool found = false;
                for (int i = 0; i < array.arraySize; i++)
                    if (array.GetArrayElementAtIndex(i).objectReferenceValue == shader) { found = true; break; }
                if (found) continue;
                array.InsertArrayElementAtIndex(array.arraySize);
                array.GetArrayElementAtIndex(array.arraySize - 1).objectReferenceValue = shader;
            }
            graphics.ApplyModifiedPropertiesWithoutUndo();
            AssetDatabase.SaveAssets();
        }
    }
}
