package com.example.personalsite.common;

/**
 * API 统一响应体。
 *
 * <p>用于保持 Java API 与 Python API 的首版响应结构一致。</p>
 *
 * @param <T> 响应数据类型
 * @author shane
 * @since 2026-06-24
 */
public class ApiResponse<T> {

    private final int code;
    private final String message;
    private final T data;

    /**
     * 创建 API 响应。
     *
     * @param code 响应码，0 表示成功
     * @param message 响应描述
     * @param data 响应数据
     */
    public ApiResponse(int code, String message, T data) {
        this.code = code;
        this.message = message;
        this.data = data;
    }

    /**
     * 创建成功响应。
     *
     * @param data 响应数据
     * @param <T> 响应数据类型
     * @return 成功响应体
     */
    public static <T> ApiResponse<T> success(T data) {
        return new ApiResponse<>(0, "success", data);
    }

    /**
     * 获取响应码。
     *
     * @return 响应码
     */
    public int getCode() {
        return code;
    }

    /**
     * 获取响应描述。
     *
     * @return 响应描述
     */
    public String getMessage() {
        return message;
    }

    /**
     * 获取响应数据。
     *
     * @return 响应数据
     */
    public T getData() {
        return data;
    }
}
