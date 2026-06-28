package com.example.personalsite.controller;

import com.example.personalsite.common.ApiResponse;
import com.example.personalsite.dto.SiteInfoResponse;
import com.example.personalsite.service.SiteInfoService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 个人站点信息 Controller。
 *
 * <p>提供前端调用的站点信息和健康检查接口。</p>
 *
 * @author shane
 * @since 2026-06-24
 */
@RestController
@RequestMapping("/api")
public class SiteController {

    private final SiteInfoService siteInfoService;

    /**
     * 创建个人站点信息 Controller。
     *
     * @param siteInfoService 站点信息 Service
     */
    public SiteController(SiteInfoService siteInfoService) {
        this.siteInfoService = siteInfoService;
    }

    /**
     * 查询 Java API 服务信息。
     *
     * @return 站点服务信息响应
     */
    @GetMapping("/site")
    public ApiResponse<SiteInfoResponse> getSiteInfo() {
        return ApiResponse.success(siteInfoService.getSiteInfo());
    }

    /**
     * 查询 Java API 健康状态。
     *
     * @return 健康状态响应
     */
    @GetMapping("/health")
    public ApiResponse<Map<String, String>> getHealth() {
        return ApiResponse.success(siteInfoService.getHealth());
    }
}
