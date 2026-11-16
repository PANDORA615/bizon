using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace RFC.Horror
{
    // Visibility culling only. All GLBs and physics remain loaded in memory.
    public sealed class RfcVisibility : MonoBehaviour
    {
        sealed class Sector
        {
            public readonly List<Renderer> renderers = new List<Renderer>();
            public Vector3 center;
            public bool visible = true;
        }
        readonly Dictionary<Vector3Int, Sector> sectors = new Dictionary<Vector3Int, Sector>();
        Transform observer;
        float radius;
        float nextUpdate;
        public bool Enabled { get; private set; } = true;

        public void Initialize(Transform viewer, IEnumerable<Renderer> renderers, float distance)
        {
            observer = viewer;
            radius = Mathf.Max(64f, distance);
            foreach (var renderer in renderers)
            {
                if (!renderer) continue;
                renderer.shadowCastingMode = ShadowCastingMode.Off;
                renderer.receiveShadows = false;
                var bounds = renderer.bounds;
                // Shared floors, walls and roof must remain visible across sectors.
                if (Mathf.Max(bounds.size.x, bounds.size.z) > 32f) continue;
                var key = new Vector3Int(Mathf.FloorToInt(bounds.center.x / 32f),
                    Mathf.FloorToInt(bounds.center.y / 4.8f), Mathf.FloorToInt(bounds.center.z / 32f));
                if (!sectors.TryGetValue(key, out var sector))
                {
                    sector = new Sector { center = new Vector3((key.x + .5f) * 32f,
                        (key.y + .5f) * 4.8f, (key.z + .5f) * 32f) };
                    sectors.Add(key, sector);
                }
                sector.renderers.Add(renderer);
            }
            Refresh();
        }

        public void Toggle()
        {
            Enabled = !Enabled;
            Refresh();
        }

        void Update()
        {
            if (Time.unscaledTime < nextUpdate) return;
            nextUpdate = Time.unscaledTime + .35f;
            Refresh();
        }

        void Refresh()
        {
            if (!observer) return;
            var pos = observer.position;
            foreach (var sector in sectors.Values)
            {
                var delta = sector.center - pos;
                bool visible = !Enabled || (delta.x * delta.x + delta.z * delta.z < (radius + 24f) * (radius + 24f)
                    && Mathf.Abs(delta.y) < 15f);
                if (visible == sector.visible) continue;
                sector.visible = visible;
                foreach (var renderer in sector.renderers) if (renderer) renderer.enabled = visible;
            }
        }
    }
}
