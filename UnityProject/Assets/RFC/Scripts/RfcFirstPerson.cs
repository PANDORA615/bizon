using UnityEngine;
using UnityEngine.InputSystem;

namespace RFC.Horror
{
    [RequireComponent(typeof(CharacterController))]
    public sealed class RfcFirstPerson : MonoBehaviour
    {
        public Camera view;
        public Light flashlight;
        public WalkSettings settings;
        CharacterController controller;
        Vector3 safePosition;
        float pitch;
        float verticalSpeed;
        bool initialized;
        public bool HasCursor => Cursor.lockState == CursorLockMode.Locked;

        public void Initialize(WalkSettings config)
        {
            settings = config;
            controller = GetComponent<CharacterController>();
            controller.height = 1.8f;
            controller.radius = 0.35f;
            controller.center = new Vector3(0f, 0.9f, 0f);
            controller.stepOffset = 0.20f;
            controller.slopeLimit = 35f;
            controller.skinWidth = 0.035f;
            controller.minMoveDistance = 0f;
            safePosition = transform.position;
            initialized = true;
            LockCursor();
        }

        public void LockCursor()
        {
            Cursor.lockState = CursorLockMode.Locked;
            Cursor.visible = false;
        }

        void Update()
        {
            if (!initialized) return;
            var keyboard = Keyboard.current;
            var mouse = Mouse.current;
            if (keyboard != null && keyboard.escapeKey.wasPressedThisFrame)
            {
                Cursor.lockState = CursorLockMode.None;
                Cursor.visible = true;
            }
            if (!HasCursor)
            {
                if (mouse != null && mouse.leftButton.wasPressedThisFrame) LockCursor();
                return;
            }
            if (mouse != null)
            {
                var look = mouse.delta.ReadValue() * settings.mouseSensitivity;
                transform.Rotate(0f, look.x, 0f, Space.World);
                pitch = Mathf.Clamp(pitch - look.y, -85f, 85f);
                view.transform.localRotation = Quaternion.Euler(pitch, 0f, 0f);
            }
            Vector2 axis = Vector2.zero;
            if (keyboard != null)
            {
                if (keyboard.wKey.isPressed || keyboard.upArrowKey.isPressed) axis.y += 1;
                if (keyboard.sKey.isPressed || keyboard.downArrowKey.isPressed) axis.y -= 1;
                if (keyboard.aKey.isPressed || keyboard.leftArrowKey.isPressed) axis.x -= 1;
                if (keyboard.dKey.isPressed || keyboard.rightArrowKey.isPressed) axis.x += 1;
                if (keyboard.fKey.wasPressedThisFrame) flashlight.enabled = !flashlight.enabled;
                if (keyboard.rKey.wasPressedThisFrame && keyboard.leftCtrlKey.isPressed) Recover();
            }
            axis = Vector2.ClampMagnitude(axis, 1f);
            float speed = keyboard != null && (keyboard.leftShiftKey.isPressed || keyboard.rightShiftKey.isPressed)
                ? settings.sprintSpeed : settings.walkSpeed;
            if (controller.isGrounded)
            {
                if (verticalSpeed < 0) verticalSpeed = -2f;
                safePosition = transform.position;
                if (keyboard != null && keyboard.spaceKey.wasPressedThisFrame)
                    verticalSpeed = Mathf.Sqrt(2f * 20f * settings.jumpHeight);
            }
            verticalSpeed -= 20f * Time.deltaTime;
            var planar = transform.right * axis.x + transform.forward * axis.y;
            controller.Move((planar * speed + Vector3.up * verticalSpeed) * Time.deltaTime);
            // Recovery is for accidental falling, never a route shortcut.
            if (transform.position.y < -8f) Recover();
        }

        void Recover()
        {
            controller.enabled = false;
            transform.position = safePosition + Vector3.up * 0.06f;
            verticalSpeed = 0f;
            controller.enabled = true;
        }

        void OnApplicationFocus(bool focused)
        {
            if (!focused) { Cursor.lockState = CursorLockMode.None; Cursor.visible = true; }
        }

        void OnDisable()
        {
            Cursor.lockState = CursorLockMode.None;
            Cursor.visible = true;
        }
    }
}
