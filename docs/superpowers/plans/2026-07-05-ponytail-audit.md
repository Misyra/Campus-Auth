# Ponytail Audit 优化计划 — 2026-07-05

基于 ponytail-audit 扫描结果，分批验证并修复。

## Batch 1 — 死代码删除（低风险）
- concurrent.py: race_first_success, cancel_pending 无调用
- time_utils.py: _parse_pause_range 无调用, is_in_pause_period 降私有
- network/utils.py: is_apipa_address 降私有
- process.py: get_process_name/get_process_create_time 降私有
- crypto.py: clear_decryption_error 降私有
- engine.py: StartResult 枚举检查
- profile_service.py: create_profile_service 别名
- launcher.py: 空 TYPE_CHECKING 块
- script_runner.py: detect_available_binaries 别名, _DEFAULT_SUBMIT_TIMEOUT 别名
- login_attempt.py: 重复导入

## Batch 2 — Shrink 内联（中风险）
- script_runner.py: get_default_binary() 内联
- interfaces.py: _is_routable_ip 内联
- browser_registry.py: _check_command_exists 内联
- probes.py: _is_captive_portal_url 内联
- playwright_worker.py: _is_orphan 内联
- profile_service.py: _rollback_config 内联
- retry_policy.py: delay_before 降私有
- detect.py: 解析逻辑合并
- step_handlers.py: _find_with_deadline 内联

## Batch 3 — 逻辑修复（需谨慎）
- crypto.py: decrypt_password_field 分支简化
- login_history_service.py: add() 统一用 atomic_write
- launcher.py: resolve_port 导入统一
- login_orchestrator.py: _bind_proxy_url 初始化
- models.py: StepConfig._field_defaults 类变量优化
- profile_service.py: deepcopy 矛盾修复
