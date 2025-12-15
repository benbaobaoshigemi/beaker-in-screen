/**
 * 二进制数据解码模块
 * 解析从后端发送的紧凑二进制粒子数据
 * 
 * 格式说明：
 * - Header: msg_type(1字节) + count(4字节)
 * - 每个粒子: x(float16, 2字节) + y(float16, 2字节) + type(uint8) + energy(uint8)
 * 
 * 使用方法：
 *     import { BinaryDecoder } from './binaryDecoder.js';
 *     const decoder = new BinaryDecoder();
 *     const particles = decoder.decodeParticles(arrayBuffer);
 */

export class BinaryDecoder {
    // 消息类型常量
    static MSG_PARTICLES = 0x01;
    static MSG_STATE = 0x02;

    constructor() {
        // Float16 解码查找表（用于快速解码）
        this.float16DecodeTable = new Float32Array(65536);
        this._initFloat16Table();
    }

    /**
     * 初始化Float16解码查找表
     * 预计算所有可能的Float16值对应的Float32值
     */
    _initFloat16Table() {
        for (let i = 0; i < 65536; i++) {
            this.float16DecodeTable[i] = this._float16ToFloat32(i);
        }
    }

    /**
     * 将Float16位模式转换为Float32
     * IEEE 754 半精度浮点数解码
     */
    _float16ToFloat32(h) {
        const sign = (h >> 15) & 0x1;
        const exponent = (h >> 10) & 0x1f;
        const mantissa = h & 0x3ff;

        let f;
        if (exponent === 0) {
            if (mantissa === 0) {
                f = 0;
            } else {
                // 次正规数
                f = Math.pow(2, -14) * (mantissa / 1024);
            }
        } else if (exponent === 31) {
            if (mantissa === 0) {
                f = Infinity;
            } else {
                f = NaN;
            }
        } else {
            f = Math.pow(2, exponent - 15) * (1 + mantissa / 1024);
        }

        return sign ? -f : f;
    }

    /**
     * 快速解码Float16（使用查找表）
     */
    decodeFloat16(byte1, byte2) {
        const bits = byte1 | (byte2 << 8);
        return this.float16DecodeTable[bits];
    }

    /**
     * 解码二进制粒子数据
     * 
     * @param {ArrayBuffer} buffer - 二进制数据
     * @returns {Array} 粒子数组 [{x, y, type, energy}, ...]
     */
    decodeParticles(buffer) {
        const view = new DataView(buffer);

        if (buffer.byteLength < 5) {
            return [];
        }

        const msgType = view.getUint8(0);
        const count = view.getUint32(1, true);  // little-endian

        if (msgType !== BinaryDecoder.MSG_PARTICLES) {
            console.warn('[BinaryDecoder] Unknown message type:', msgType);
            return [];
        }

        if (buffer.byteLength < 5 + count * 6) {
            console.warn('[BinaryDecoder] Buffer too small for', count, 'particles');
            return [];
        }

        const particles = new Array(count);
        const bytes = new Uint8Array(buffer);

        for (let i = 0; i < count; i++) {
            const offset = 5 + i * 6;

            // 解码Float16 x坐标
            const x = this.decodeFloat16(bytes[offset], bytes[offset + 1]);
            // 解码Float16 y坐标
            const y = this.decodeFloat16(bytes[offset + 2], bytes[offset + 3]);
            // 类型
            const type = bytes[offset + 4];
            // 能量 (归一化到 [0, 1])
            const energy = bytes[offset + 5] / 255.0;

            particles[i] = { x, y, type, energy };
        }

        return particles;
    }

    /**
     * 检查是否为二进制消息
     */
    static isBinaryMessage(data) {
        return data instanceof ArrayBuffer || data instanceof Blob;
    }
}

// 单例实例
export const binaryDecoder = new BinaryDecoder();
