package com.example.personalsite.service;

import com.example.personalsite.dto.SiteInfoResponse;

import java.util.Map;

/**
 * 个人站点服务信息 Service。
 *
 * <p>负责提供 Java 后端的站点信息和健康状态。</p>
 *
 * @author shane
 * @since 2026-06-24
 */
public interface SiteInfoService {

    /**
     * 查询当前 Java API 服务信息。
     *
     * @return 服务信息
     */
    SiteInfoResponse getSiteInfo();

    /**
     * 查询当前 Java API 健康状态。
     *
     * @return 健康状态键值
     */
    Map<String, String> getHealth();
}
