using System.Collections.Generic;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.Rendering;

namespace RFC.Horror
{
    public sealed class RfcLighting : MonoBehaviour
    {
        readonly List<LightRecord> anchors = new List<LightRecord>();
        readonly List<Light> pool = new List<Light>();
        readonly List<int> nearest = new List<int>();
        readonly List<float> distances = new List<float>();
        Transform viewer;
        Light sun;
        float nextUpdate;
        public bool Night { get; private set; }
        public const int LightBudget = 12;

        public void Initialize(Transform observer, LightRecord[] records)
        {
            viewer = observer;
            // Reuse exported floor-level task anchors. Emergency and night lighting
            // are applied to a bounded light pool rather than hundreds of active lights.
            foreach (var record in records)
                if (record.group == "LOCAL_TASK" || record.group == "EMERGENCY_RED") anchors.Add(record);
            for (int i = 0; i < LightBudget; i++)
            {
                var go = new GameObject("Local light " + i);
                go.transform.SetParent(transform, false);
                var light = go.AddComponent<Light>();
                light.type = LightType.Point;
                light.shadows = LightShadows.None;
                light.renderMode = LightRenderMode.Auto;
                light.enabled = false;
                pool.Add(light);
            }
            var sunObject = new GameObject("Warehouse daylight");
            sunObject.transform.SetParent(transform, false);
            sun = sunObject.AddComponent<Light>();
            sun.type = LightType.Directional;
            sun.shadows = LightShadows.None;
            sun.transform.rotation = Quaternion.Euler(55f, -25f, 0f);
            RenderSettings.sun = sun;
            RenderSettings.ambientMode = AmbientMode.Flat;
            SetNight(false);
        }

        public void SetNight(bool value)
        {
            Night = value;
            // Broad ambient lighting deliberately keeps floors and exits legible.
            RenderSettings.ambientLight = value ? new Color(.11f, .14f, .19f) : new Color(.48f, .52f, .58f);
            RenderSettings.ambientIntensity = 1f;
            if (sun) { sun.intensity = value ? .035f : .65f; sun.color = new Color(.75f, .85f, 1f); }
            RenderSettings.fog = true;
            RenderSettings.fogMode = FogMode.Linear;
            RenderSettings.fogColor = value ? new Color(.035f, .05f, .065f) : new Color(.28f, .33f, .38f);
            RenderSettings.fogStartDistance = value ? 60f : 110f;
            RenderSettings.fogEndDistance = value ? 160f : 220f;
            nextUpdate = 0f;
        }

        void Update()
        {
            if (!viewer) return;
            if (Keyboard.current != null && Keyboard.current.nKey.wasPressedThisFrame) SetNight(!Night);
            if (Time.unscaledTime < nextUpdate) return;
            nextUpdate = Time.unscaledTime + .35f;
            nearest.Clear(); distances.Clear();
            var position = viewer.position;
            for (int i = 0; i < anchors.Count; i++)
            {
                var record = anchors[i];
                if (!Night && record.group == "EMERGENCY_RED") continue;
                var point = RfcCoordinates.Position(record.position_m);
                float height = point.y - position.y;
                if (height < -.5f || height > 5f) continue;
                float distance = (point - position).sqrMagnitude;
                if (distance > 80f * 80f) continue;
                int index = distances.BinarySearch(distance);
                if (index < 0) index = ~index;
                if (index >= LightBudget) continue;
                distances.Insert(index, distance); nearest.Insert(index, i);
                if (nearest.Count > LightBudget) { nearest.RemoveAt(LightBudget); distances.RemoveAt(LightBudget); }
            }
            for (int i = 0; i < pool.Count; i++)
            {
                var light = pool[i]; light.enabled = i < nearest.Count;
                if (!light.enabled) continue;
                var anchor = anchors[nearest[i]];
                light.transform.position = RfcCoordinates.Position(anchor.position_m);
                light.color = new Color(anchor.color[0], anchor.color[1], anchor.color[2]);
                light.range = anchor.group == "EMERGENCY_RED" ? 10f : 24f;
                light.intensity = anchor.group == "EMERGENCY_RED" ? 1.2f : (Night ? 1.0f : 2.8f);
            }
        }
    }
}
