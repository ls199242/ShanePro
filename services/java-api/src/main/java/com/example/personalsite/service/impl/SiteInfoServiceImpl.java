package com.example.personalsite.service.impl;

import com.example.personalsite.dto.SiteInfoResponse;
import com.example.personalsite.service.SiteInfoService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 个人站点服务信息 Service 实现。
 *
 * <p>返回当前 Java API 的服务信息，用于前端展示和健康检查。</p>
 *
 * @author shane
 * @since 2026-06-24
 */
@Service
public class SiteInfoServiceImpl implements SiteInfoService {

    private static final Logger log = LoggerFactory.getLogger(SiteInfoServiceImpl.class);

    /**
     * 查询当前 Java API 服务信息。
     *
     * @return 服务信息
     */
    @Override
    public SiteInfoResponse getSiteInfo() {
        log.info("[站点信息] 返回 Java API 服务信息");
        return new SiteInfoResponse("java-api", "Java", "UP", "Spring Boot service for Shane's personal site");
    }

    /**
     * 查询当前 Java API 健康状态。
     *
     * @return 健康状态键值
     */
    @Override
    public Map<String, String> getHealth() {
        log.info("[健康检查] Java API 服务健康");
        Map<String, String> health = new LinkedHashMap<>();
        health.put("service", "java-api");
        health.put("status", "UP");
        return health;
    }
}
