/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.termux.x11.input;

import android.content.Context;
import android.hardware.input.InputManager;
import android.util.Log;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.net.SocketTimeoutException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

/** Android gamepad to a bounded localhost XInput transport. */
public final class GamepadBridge implements AutoCloseable, InputManager.InputDeviceListener {
    private static final String TAG = "TermuxX11Gamepad";
    private static final int PACKET_SIZE = 64;
    private static final int CLIENT_PORT = 4600;
    private static final int SERVER_PORT = 4602;
    private static final int GAMEPAD_ID = 1;
    private static final int CODE_HELLO = 1;
    private static final int CODE_GET_GAMEPAD = 8;
    private static final int CODE_GAMEPAD_STATE = 9;
    private static final int CODE_RELEASE_GAMEPAD = 10;
    private static final int FLAG_INPUT_TYPE_XINPUT = 0x04;

    private final Object lock = new Object();
    private final InputManager inputManager;
    private volatile DatagramSocket socket;
    private volatile SocketAddress peer;
    private Thread thread;
    private volatile boolean running;
    private volatile int activeDeviceId = -1;
    private int buttons;
    private int dpadDirections;
    private int leftX;
    private int leftY;
    private int rightX;
    private int rightY;
    private int leftTrigger;
    private int rightTrigger;

    public GamepadBridge(Context context) {
        inputManager = (InputManager) context.getApplicationContext()
                .getSystemService(Context.INPUT_SERVICE);
    }

    public void start() {
        if (running) return;
        try {
            DatagramSocket candidate = new DatagramSocket(null);
            candidate.setReuseAddress(false);
            candidate.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), CLIENT_PORT));
            candidate.setSoTimeout(250);
            socket = candidate;
            running = true;
            if (inputManager != null) {
                inputManager.registerInputDeviceListener(this, null);
                scanControllers();
            }
            thread = new Thread(this::receiveLoop, "TermuxX11-Gamepad");
            thread.setDaemon(true);
            thread.start();
            Log.i(TAG, "listening on 127.0.0.1:" + CLIENT_PORT);
        } catch (Exception error) {
            Log.e(TAG, "cannot start gamepad bridge", error);
            close();
        }
    }

    @Override
    public void close() {
        running = false;
        if (inputManager != null)
            inputManager.unregisterInputDeviceListener(this);
        DatagramSocket current = socket;
        socket = null;
        peer = null;
        if (current != null) current.close();
        Thread currentThread = thread;
        thread = null;
        if (currentThread != null && currentThread != Thread.currentThread()) {
            try {
                currentThread.join(500);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        }
    }

    public boolean handleKey(KeyEvent event) {
        if (event == null || !acceptDevice(event.getDevice())) return false;
        int action = event.getAction();
        if (action != KeyEvent.ACTION_DOWN && action != KeyEvent.ACTION_UP) return false;
        boolean pressed = action == KeyEvent.ACTION_DOWN;
        int bit = buttonBit(event.getKeyCode());
        int direction = dpadBit(event.getKeyCode());
        if (bit == 0 && direction == 0) return false;
        synchronized (lock) {
            if (bit != 0) {
                if (pressed) buttons |= bit;
                else buttons &= ~bit;
            }
            if (direction != 0) {
                if (pressed) dpadDirections |= direction;
                else dpadDirections &= ~direction;
            }
        }
        sendState();
        return true;
    }

    public boolean handleMotion(MotionEvent event) {
        if (event == null || !acceptDevice(event.getDevice())) return false;
        synchronized (lock) {
            leftX = axis(event, MotionEvent.AXIS_X);
            leftY = axis(event, MotionEvent.AXIS_Y);
            float rx = event.getAxisValue(MotionEvent.AXIS_Z);
            float ry = event.getAxisValue(MotionEvent.AXIS_RZ);
            if (rx == 0f && ry == 0f) {
                rx = event.getAxisValue(MotionEvent.AXIS_RX);
                ry = event.getAxisValue(MotionEvent.AXIS_RY);
            }
            rightX = axis(rx);
            rightY = axis(ry);
            float lt = Math.max(
                    event.getAxisValue(MotionEvent.AXIS_LTRIGGER),
                    event.getAxisValue(MotionEvent.AXIS_BRAKE));
            float rt = Math.max(
                    event.getAxisValue(MotionEvent.AXIS_RTRIGGER),
                    event.getAxisValue(MotionEvent.AXIS_GAS));
            leftTrigger = trigger(lt);
            rightTrigger = trigger(rt);
            updateHat(event.getAxisValue(MotionEvent.AXIS_HAT_X),
                    event.getAxisValue(MotionEvent.AXIS_HAT_Y));
        }
        sendState();
        return true;
    }

    private void receiveLoop() {
        byte[] bytes = new byte[PACKET_SIZE];
        DatagramPacket packet = new DatagramPacket(bytes, bytes.length);
        while (running) {
            try {
                packet.setLength(bytes.length);
                socket.receive(packet);
                if (!isExpectedPeer(packet.getSocketAddress())) continue;
                int code = bytes[0] & 0xff;
                if (code == CODE_HELLO) {
                    peer = packet.getSocketAddress();
                } else if (code == CODE_GET_GAMEPAD && packet.getLength() >= 6
                        && bytes[1] == 1 && readInt(bytes, 2) == GAMEPAD_ID) {
                    peer = packet.getSocketAddress();
                    if (activeDeviceId >= 0) {
                        sendHandshake();
                        sendState();
                    } else {
                        sendRelease();
                    }
                } else if (code == CODE_RELEASE_GAMEPAD) {
                    peer = null;
                }
            } catch (SocketTimeoutException timeout) {
                sendState();
            } catch (Exception error) {
                if (running) Log.e(TAG, "gamepad receive failed", error);
            }
        }
    }

    private static boolean isExpectedPeer(SocketAddress address) {
        if (!(address instanceof InetSocketAddress)) return false;
        InetSocketAddress inet = (InetSocketAddress) address;
        return inet.getPort() == SERVER_PORT
                && inet.getAddress() != null
                && inet.getAddress().isLoopbackAddress();
    }

    private void sendHandshake() {
        if (activeDeviceId < 0) return;
        byte[] bytes = new byte[PACKET_SIZE];
        ByteBuffer buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        buffer.put(0, (byte) CODE_GET_GAMEPAD);
        buffer.put(1, (byte) 1);
        buffer.putInt(2, GAMEPAD_ID);
        buffer.put(6, (byte) FLAG_INPUT_TYPE_XINPUT);
        byte[] name = "Termux:X11 Gamepad".getBytes(StandardCharsets.UTF_8);
        System.arraycopy(name, 0, bytes, 7, name.length);
        send(bytes);
    }

    private void sendState() {
        if (activeDeviceId < 0) return;
        byte[] bytes = new byte[PACKET_SIZE];
        ByteBuffer buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        synchronized (lock) {
            buffer.put(0, (byte) CODE_GAMEPAD_STATE);
            buffer.put(1, (byte) 1);
            buffer.putInt(2, GAMEPAD_ID);
            buffer.putShort(6, (short) buttons);
            buffer.put(8, (byte) dpadValue());
            buffer.putShort(9, (short) leftX);
            buffer.putShort(11, (short) leftY);
            buffer.putShort(13, (short) rightX);
            buffer.putShort(15, (short) rightY);
            buffer.put(17, (byte) leftTrigger);
            buffer.put(18, (byte) rightTrigger);
        }
        send(bytes);
    }

    private void send(byte[] bytes) {
        DatagramSocket current = socket;
        SocketAddress target = peer;
        if (!running || current == null || target == null) return;
        try {
            current.send(new DatagramPacket(bytes, bytes.length, target));
        } catch (Exception error) {
            if (running) Log.e(TAG, "gamepad send failed", error);
        }
    }

    private void sendRelease() {
        byte[] bytes = new byte[PACKET_SIZE];
        bytes[0] = (byte) CODE_RELEASE_GAMEPAD;
        bytes[1] = 1;
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
                .putInt(2, GAMEPAD_ID);
        send(bytes);
    }

    private boolean acceptDevice(InputDevice device) {
        if (!isController(device)) return false;
        int deviceId = device.getId();
        synchronized (lock) {
            if (activeDeviceId < 0) {
                activeDeviceId = deviceId;
                clearStateLocked();
                Log.i(TAG, "controller connected id=" + deviceId + " name=" + device.getName());
                sendHandshake();
            }
            return activeDeviceId == deviceId;
        }
    }

    private void scanControllers() {
        int selected = -1;
        for (int deviceId : InputDevice.getDeviceIds()) {
            InputDevice device = InputDevice.getDevice(deviceId);
            if (isController(device) && (selected < 0 || deviceId < selected))
                selected = deviceId;
        }
        setActiveDevice(selected);
    }

    private void setActiveDevice(int deviceId) {
        int previous;
        synchronized (lock) {
            previous = activeDeviceId;
            if (previous == deviceId) return;
            activeDeviceId = deviceId;
            clearStateLocked();
        }
        if (deviceId < 0) {
            Log.i(TAG, "controller disconnected id=" + previous);
            sendRelease();
        } else {
            InputDevice device = InputDevice.getDevice(deviceId);
            Log.i(TAG, "controller connected id=" + deviceId + " name="
                    + (device == null ? "unknown" : device.getName()));
            sendHandshake();
            sendState();
        }
    }

    private void clearStateLocked() {
        buttons = 0;
        dpadDirections = 0;
        leftX = 0;
        leftY = 0;
        rightX = 0;
        rightY = 0;
        leftTrigger = 0;
        rightTrigger = 0;
    }

    private static boolean isController(InputDevice device) {
        return device != null && !device.isVirtual() && isGamepad(device.getSources());
    }

    @Override
    public void onInputDeviceAdded(int deviceId) {
        scanControllers();
    }

    @Override
    public void onInputDeviceRemoved(int deviceId) {
        scanControllers();
    }

    @Override
    public void onInputDeviceChanged(int deviceId) {
        scanControllers();
    }

    private static boolean isGamepad(int source) {
        return (source & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD
                || (source & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK;
    }

    private static int buttonBit(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_BUTTON_A: return 1 << 0;
            case KeyEvent.KEYCODE_BUTTON_B: return 1 << 1;
            case KeyEvent.KEYCODE_BUTTON_X: return 1 << 2;
            case KeyEvent.KEYCODE_BUTTON_Y: return 1 << 3;
            case KeyEvent.KEYCODE_BUTTON_L1: return 1 << 4;
            case KeyEvent.KEYCODE_BUTTON_R1: return 1 << 5;
            case KeyEvent.KEYCODE_BUTTON_START:
            case KeyEvent.KEYCODE_BUTTON_MODE: return 1 << 6;
            case KeyEvent.KEYCODE_BUTTON_SELECT:
            case KeyEvent.KEYCODE_BACK: return 1 << 7;
            case KeyEvent.KEYCODE_BUTTON_THUMBL: return 1 << 8;
            case KeyEvent.KEYCODE_BUTTON_THUMBR: return 1 << 9;
            default: return 0;
        }
    }

    private static int dpadBit(int keyCode) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_UP: return 1;
            case KeyEvent.KEYCODE_DPAD_RIGHT: return 2;
            case KeyEvent.KEYCODE_DPAD_DOWN: return 4;
            case KeyEvent.KEYCODE_DPAD_LEFT: return 8;
            default: return 0;
        }
    }

    private void updateHat(float x, float y) {
        int value = 0;
        if (y < -0.5f) value |= 1;
        if (x > 0.5f) value |= 2;
        if (y > 0.5f) value |= 4;
        if (x < -0.5f) value |= 8;
        dpadDirections = value;
    }

    private int dpadValue() {
        switch (dpadDirections) {
            case 1: return 0;
            case 3: return 1;
            case 2: return 2;
            case 6: return 3;
            case 4: return 4;
            case 12: return 5;
            case 8: return 6;
            case 9: return 7;
            default: return 255;
        }
    }

    private static int axis(MotionEvent event, int code) {
        return axis(event.getAxisValue(code));
    }

    private static int axis(float value) {
        float bounded = Math.max(-1f, Math.min(1f, value));
        return Math.round(bounded * 32767f);
    }

    private static int trigger(float value) {
        return Math.round(Math.max(0f, Math.min(1f, value)) * 255f);
    }

    private static int readInt(byte[] bytes, int offset) {
        return ByteBuffer.wrap(bytes, offset, 4).order(ByteOrder.LITTLE_ENDIAN).getInt();
    }
}
