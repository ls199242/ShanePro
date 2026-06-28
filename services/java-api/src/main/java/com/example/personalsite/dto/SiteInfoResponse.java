package com.example.personalsite.dto;

/**
 * 站点服务信息响应。
 *
 * <p>描述当前后端服务的名称、实现语言、运行状态和说明文案。</p>
 *
 * @author shane
 * @since 2026-06-24
 */
public class SiteInfoResponse {

    private final String service;
    private final String language;
    private final String status;
    private final String description;

    /**
     * 创建站点服务信息响应。
     *
     * @param service 服务标识
     * @param language 实现语言
     * @param status 运行状态
     * @param description 服务说明
     */
    public SiteInfoResponse(String service, String language, String status, String description) {
        this.service = service;
        this.language = language;
        this.status = status;
        this.description = description;
    }

    /**
     * 获取服务标识。
     *
     * @return 服务标识
     */
    public String getService() {
        return service;
    }

    /**
     * 获取实现语言。
     *
     * @return 实现语言
     */
    public String getLanguage() {
        return language;
    }

    /**
     * 获取运行状态。
     *
     * @return 运行状态
     */
    public String getStatus() {
        return status;
    }

    /**
     * 获取服务说明。
     *
     * @return 服务说明
     */
    public String getDescription() {
        return description;
    }
}
