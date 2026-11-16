using System;
using UnityEngine;

namespace RFC.Horror
{
    [Serializable] public sealed class RfcEnvelope<T> { public T data; }
    [Serializable] public sealed class ColliderRecord
    {
        public string id;
        public string kind;
        public string sector_id;
        public float[] position_m;
        public float[] size_m;
        public float[] rotation_euler_rad;
    }
    [Serializable] public sealed class LightRecord
    {
        public string id;
        public string group;
        public float energy_w;
        public float[] position_m;
        public float[] color;
        public string block;
        public int floor;
    }
    [Serializable] public sealed class WalkSettings
    {
        public float walkSpeed = 2.5f;
        public float sprintSpeed = 7f;
        public float mouseSensitivity = 0.12f;
        public float jumpHeight = 0.65f;
        public float renderDistance = 160f;
        public float[] spawnBlender = new[] { 66f, 160f, 0.12f };
    }

    public static class RfcCoordinates
    {
        // Canonical Unity world: Blender (x,y,z) -> Unity (x,z,y).
        // glTFast mirrors X on import; rotate its visual parent 180 degrees about Y.
        public static Vector3 Position(float[] v) => new Vector3(v[0], v[2], v[1]);
        public static Vector3 Size(float[] v) => new Vector3(v[0], v[2], v[1]);
        public static Quaternion Rotation(float[] xyz)
        {
            // Blender Euler XYZ is Rz * Ry * Rx. A reflection transforms the
            // quaternion vector by det(S)*S, not by swapping Euler angles.
            var q = Quaternion.AngleAxis(xyz[2] * Mathf.Rad2Deg, Vector3.forward)
                  * Quaternion.AngleAxis(xyz[1] * Mathf.Rad2Deg, Vector3.up)
                  * Quaternion.AngleAxis(xyz[0] * Mathf.Rad2Deg, Vector3.right);
            return new Quaternion(-q.x, -q.z, -q.y, q.w);
        }
    }
}
