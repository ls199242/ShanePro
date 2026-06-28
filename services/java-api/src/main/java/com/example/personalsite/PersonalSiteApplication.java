package com.example.personalsite;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 个人站点 Java API 启动类。
 *
 * <p>负责启动 Spring Boot Web 服务，为前端提供 Java 后端接口。</p>
 *
 * @author shane
 * @since 2026-06-24
 */
@SpringBootApplication
public class PersonalSiteApplication {

    /**
     * 启动 Java API 服务。
     *
     * @param args 命令行参数
     */
    public static void main(String[] args) {
        SpringApplication.run(PersonalSiteApplication.class, args);
    }
}
