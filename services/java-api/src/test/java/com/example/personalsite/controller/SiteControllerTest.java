package com.example.personalsite.controller;

import com.example.personalsite.service.SiteInfoService;
import com.example.personalsite.service.impl.SiteInfoServiceImpl;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 个人站点信息 Controller 测试。
 *
 * <p>验证 Java API 接口契约和统一响应结构。</p>
 *
 * @author shane
 * @since 2026-06-24
 */
class SiteControllerTest {

    private MockMvc mockMvc;

    private SiteInfoService siteInfoService;

    @BeforeEach
    void setUp() {
        siteInfoService = new SiteInfoServiceImpl();
        mockMvc = MockMvcBuilders.standaloneSetup(new SiteController(siteInfoService)).build();
    }

    @Test
    void getSiteInfoReturnsUnifiedResponse() throws Exception {
        mockMvc.perform(get("/api/site"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.message").value("success"))
                .andExpect(jsonPath("$.data.service").value("java-api"))
                .andExpect(jsonPath("$.data.language").value("Java"))
                .andExpect(jsonPath("$.data.status").value("UP"))
                .andExpect(jsonPath("$.data.description").value("Spring Boot service for Shane's personal site"));
    }

    @Test
    void getHealthReturnsUnifiedResponse() throws Exception {
        mockMvc.perform(get("/api/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.message").value("success"))
                .andExpect(jsonPath("$.data.service").value("java-api"))
                .andExpect(jsonPath("$.data.status").value("UP"));
    }
}
