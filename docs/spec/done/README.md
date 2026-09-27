# 阶段完成文档归档

> ✅ **本目录已入库**（2026-09-27 起）。`.gitignore` 以 `docs/spec/*` + `!docs/spec/done/`
> 放行本目录下的完成文档；计划书、阶段任务书与模板**仍仅本地保留**。
>
> 该放行是 `done/stage-10-completion.md` 第 5 节**方案 B 的提前落地，项目群裁定尚未追认**——
> 若裁定推翻，回滚 `.gitignore` 那两行即可。
>
> 注意 `docs/spec/*` 的写法不能写成 `docs/spec/`：父目录被排除后 git 不会进入该目录，
> `!` 白名单会失效。原因已写在 `.gitignore` 原位注释里。

每个阶段验收测试通过后，把 `docs/spec/templates/stage-completion-template.md`
复制到本目录，命名为 `stage-NN-completion.md`（NN 与阶段号一致，如 `stage-00-completion.md`），**当天填完**。

- 补写的完成文档没有证据价值——证据要趁热留
- 阶段 7 的完成文档**必须附覆盖率报告的完整原始输出**，不接受"已通过"三个字
- 偏离计划之处必须如实写：工时超了、范围砍了、验收标准被迫放宽，都要记

完成后回到 `docs/spec/README.md` 第 5 节更新阶段状态表。
