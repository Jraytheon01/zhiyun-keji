(function () {
  "use strict";

  const ROUTE = () => location.hash.replace(/^#/, "") || "home";
  const KEY = { learner: "zyk.learnerId", course: "zyk.courseId", run: "zyk.runId", prompt: "zyk.handoffPrompt" };
  const ACTIONS = {
    course_review: "复盘课程",
    mind_map: "生成思维导图",
    learning_check: "学习检测",
    cross_course_review: "跨课回顾",
    study_plan: "生成学习建议",
  };
  const state = {
    learnerId: localStorage.getItem(KEY.learner) || "",
    courseId: localStorage.getItem(KEY.course) || "",
    runId: localStorage.getItem(KEY.run) || "",
    handoffPrompt: sessionStorage.getItem(KEY.prompt) || "",
    action: "learning_check",
    focus: "本课核心内容",
    bootstrap: null,
    course: null,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[char]);
  const dateText = (value) => {
    if (!value) return "时间未记录";
    const date = new Date(String(value).replace(" ", "T"));
    return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(date);
  };
  const timeText = (value) => {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat("zh-CN", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    }).format(date);
  };
  const go = (route) => { location.hash = route.replace(/\.html$/, ""); };
  const toast = (message, danger = false) => {
    const target = $(".toast");
    if (!target) return;
    target.textContent = message;
    target.classList.toggle("danger", danger);
    target.classList.add("show");
    setTimeout(() => target.classList.remove("show"), 3600);
  };

  async function copyText(value) {
    const text = String(value || "");
    if (!text) throw new Error("Prompt 尚未生成")
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); return; } catch (_) { /* use the browser compatibility path below */ }
    }
    const area = document.createElement("textarea");
    area.value = text; area.setAttribute("readonly", "");
    area.style.position = "fixed"; area.style.opacity = "0";
    document.body.appendChild(area); area.select();
    const copied = document.execCommand("copy"); area.remove();
    if (!copied) throw new Error("浏览器未允许复制，请在页面中手动复制 Prompt");
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `请求失败（${response.status}）`);
    return data;
  }

  function withLearner(path) {
    const separator = path.includes("?") ? "&" : "?";
    return `${path}${separator}learner_id=${encodeURIComponent(state.learnerId)}`;
  }

  function setCourse(courseId) {
    state.courseId = String(courseId || "");
    if (state.courseId) localStorage.setItem(KEY.course, state.courseId);
  }

  function selectedCourse() {
    return state.bootstrap?.courses?.find((item) => String(item.course_id) === String(state.courseId))
      || state.bootstrap?.courses?.[0] || null;
  }

  function courseCard(course) {
    const ready = course.status === "ready";
    return `<article class="card course-card platform-course" data-course-id="${esc(course.course_id)}">
      <div class="course-glyph" aria-hidden="true"><span>课</span></div>
      <div class="course-main">
        <div class="meta-row"><span>${esc(course.subject || "课程")} · ${esc(course.grade || "学习记录")}</span>
          <span class="badge ${ready ? "ready" : "pending"}">${ready ? "内容已就绪" : esc(course.status || "处理中")}</span></div>
        <h3>${esc(course.title)}</h3>
        <div class="meta-row"><span>${esc(dateText(course.create_time))}</span><span>${esc(course.duration_text || "时长未记录")}</span>
          <span>${esc(course.scene || "课堂记录")}</span><span class="source-tag">${course.source === "mysql" ? "课堂内容" : "导入内容"}</span></div>
      </div>
      <div class="course-side"><button class="btn btn-ghost js-view-course" data-course-id="${esc(course.course_id)}">查看课程</button>
        <button class="btn btn-secondary js-open-platform-drawer" data-course-id="${esc(course.course_id)}" data-action="course_review">和 TeleAgent 聊聊</button></div>
    </article>`;
  }

  function installLearnerPicker() {
    const host = $(".student");
    const learners = state.bootstrap?.learners || [];
    const current = state.bootstrap?.learner || {};
    if (!host) return;
    host.innerHTML = `<span class="avatar">${esc((current.display_name || "学").slice(0, 1))}</span>
      <label class="learner-picker"><span>当前学习者</span>
        <select class="learner-select" aria-label="切换学习者">${learners.map((learner) => `<option value="${esc(learner.learner_id)}" ${String(learner.learner_id) === String(state.learnerId) ? "selected" : ""}>${esc(learner.display_name || `学习者 ${learner.learner_id}`)}</option>`).join("")}</select>
      </label>`;
    $(".learner-select", host)?.addEventListener("change", (event) => {
      localStorage.setItem(KEY.learner, event.target.value);
      localStorage.removeItem(KEY.course);
      localStorage.removeItem(KEY.run);
      location.reload();
    });
  }

  function hydrateCommon() {
    const learner = state.bootstrap.learner;
    installLearnerPicker();
    document.title = `${learner.display_name || "学习者"} · 智云课迹`;
    const growthNav = $("[data-od-id='nav-growth'] span");
    if (growthNav) growthNav.textContent = "学习成长";
    $$(".js-open-drawer").forEach((button) => button.classList.add("js-open-platform-drawer"));
    $$(".js-open-drawer, .js-open-platform-drawer").forEach((button) => {
      if (/发送到\s*TeleAgent|再次发送到\s*TeleAgent|生成\s*TeleAgent\s*Prompt/.test(button.textContent)) {
        button.textContent = "和 TeleAgent 聊聊";
      }
    });
  }

  function hydrateHome() {
    const learner = state.bootstrap.learner;
    const growth = state.bootstrap.growth || {};
    const plans = growth.plans || [];
    const events = growth.events || [];
    const mastery = growth.mastery || [];
    const title = $(".page-title");
    const sub = $(".page-sub");
    if (title) title.textContent = `${learner.display_name || "学习者"}的学习工作台`;
    if (sub) sub.textContent = `已沉淀 ${state.bootstrap.courses.length} 堂课程，课程依据、TeleAgent 互动和成长变化在这里持续连接。`;
    const head = $(".page-head");
    if (head && !$(".ai-presence-strip")) head.insertAdjacentHTML("afterend", `<section class="ai-presence-strip">
      <span class="ai-orb" aria-hidden="true"><i></i></span><div><strong>课迹 AI 正在整理你的学习线索</strong><small>课程原文、TeleAgent 对话与长期记忆已按证据关联</small></div>
      <button class="btn btn-ghost" data-go="growth-overview">查看 AI 发现</button></section>`);
    const courseGrid = $("[data-od-id='recent-courses'] .grid");
    if (courseGrid) courseGrid.innerHTML = state.bootstrap.courses.length
      ? state.bootstrap.courses.slice(0, 2).map(courseCard).join("")
      : emptyState("还没有课程", "从录音、视频、逐字稿或演示内容建立第一堂课程。", "add-course", "添加课程");
    const hero = $("[data-od-id='primary-next-action']");
    const next = plans.find((item) => item.status === "today") || plans[0];
    if (hero) hero.innerHTML = `<div class="eyebrow">当前最值得做 · 有依据的下一步</div>
      <h2>${esc(next?.title || "选择一堂课程完成第一次复盘")}</h2>
      <p>${esc(next?.reason || "平台会把真实课程内容交给 TeleAgent，并把完成结果受控回流到成长档案。")}</p>
      <div class="meta-row"><span>约 ${esc(next?.minutes || 5)} 分钟</span><span>${esc(next?.knowledge_point || "课程主线")}</span></div>
      <div class="actions"><button class="btn btn-primary js-open-platform-drawer" data-action="${next ? "learning_check" : "course_review"}">和 TeleAgent 聊聊</button>
      <button class="btn btn-ghost js-go-course">查看课程依据</button></div>`;
    const planCard = $("[data-od-id='home-plans']");
    if (planCard) planCard.innerHTML = `<div class="section-head"><h2>学习计划</h2><span class="badge pending">${plans.length} 项</span></div><div class="plan-list">${plans.slice(0, 3).map((item, index) => `<div class="plan-item"><span class="step-no">${String(index + 1).padStart(2, "0")}</span><div><strong>${esc(item.title)}</strong><small>${esc(item.minutes || 5)} 分钟 · ${esc(item.knowledge_point || "课程主线")}</small></div></div>`).join("") || `<p class="muted-copy">完成一次课程复盘后，平台 AI 会根据真实记录生成下一步。</p>`}</div>`;
    const interactionCard = $("[data-od-id='recent-results'] .card:first-child .event-list");
    if (interactionCard) interactionCard.innerHTML = events.length ? events.slice(0, 3).map((event) => `<div class="event-item">
      <span class="step-no">${esc(timeText(event.created_at))}</span><div><strong>${esc(event.title)}</strong><small>${esc(event.description)}</small></div><span class="badge ready">已留痕</span></div>`).join("") : `<p class="muted-copy">完成 TeleAgent 任务后，结果会在这里留下可追溯记录。</p>`;
    const changeCard = $("[data-od-id='recent-results'] .card:last-child");
    const weak = mastery.find((item) => item.level === "待巩固") || mastery[0];
    if (changeCard) changeCard.innerHTML = `<div class="eyebrow">最近成长状态</div><h2>${esc(weak?.knowledge_point || "等待第一次有效互动")}</h2>
      <div class="trace"><span class="trace-node">${esc(weak?.level || "尚无状态")}<small>${esc(weak?.evidence_count ? `${weak.evidence_count} 条证据` : "不会凭课堂出现直接判定掌握")}</small></span></div>
      <p>${esc(weak?.last_reason || "只有真实作答或明确互动结果才会改变掌握状态。")}</p>`;
  }

  function emptyState(title, copy, route, action) {
    return `<article class="card empty-state"><span class="empty-mark">迹</span><h2>${esc(title)}</h2><p>${esc(copy)}</p>${route ? `<button class="btn btn-primary" data-go="${esc(route)}">${esc(action)}</button>` : ""}</article>`;
  }

  function hydrateCourses() {
    const grid = $("[data-od-id='course-list']");
    if (!grid) return;
    grid.innerHTML = state.bootstrap.courses.length ? state.bootstrap.courses.map(courseCard).join("")
      : emptyState("课程档案还是空的", "这里管理真实课程内容，不承担录音设备或通用学习应用的角色。", "add-course", "添加第一堂课程");
    const search = $(".search");
    search?.addEventListener("input", () => {
      const key = search.value.trim().toLowerCase();
      $$(".platform-course", grid).forEach((card) => { card.hidden = !card.textContent.toLowerCase().includes(key); });
    });
  }

  function reviewHtml(reviewWrapper, course) {
    if (!reviewWrapper?.payload) return `<div class="reading-block review-empty"><span class="ai-label">等待 AI 复盘</span>
      <h2>先把课堂内容变成可继续行动的依据</h2>${course.summary ? `<p>${esc(course.summary)}</p>` : ""}
      <button class="btn btn-primary js-generate-review">生成 AI 复盘</button></div>`;
    const review = reviewWrapper.payload;
    const points = review.knowledge_points || [];
    const misconceptions = review.misconceptions || [];
    return `<div class="reading-block"><span class="ai-label">AI 生成 · 可回到原文</span><h2>课程主线</h2><p>${esc(review.summary)}</p></div>
      <div class="reading-block"><h2>学习目标</h2><ol class="clean-list">${(review.objectives || []).map((item) => `<li>${esc(item)}</li>`).join("")}</ol></div>
      <div class="reading-block"><h2>核心知识点</h2><div class="evidence-list">${points.map((point, index) => `<div class="evidence-item"><span class="step-no">${String(index + 1).padStart(2, "0")}</span>
        <div><strong>${esc(point.name)}</strong><p>${esc(point.explanation)}</p>${point.evidence_quote ? `<blockquote class="source-quote">${esc(point.evidence_quote)}</blockquote>` : ""}${point.review_prompt ? `<small>${esc(point.review_prompt)}</small>` : ""}</div><span class="badge pending">待作答验证</span></div>`).join("")}</div></div>
      ${misconceptions.length ? `<div class="reading-block"><h2>易错提醒</h2>${misconceptions.map((item) => `<div class="quote"><strong>${esc(item.name)}</strong><br>${esc(item.explanation)}${item.evidence_quote ? `<small class="evidence-caption">依据：${esc(item.evidence_quote)}</small>` : ""}</div>`).join("")}</div>` : ""}
      ${review.next_action?.title ? `<div class="reading-block"><h2>建议下一步</h2><p>${esc(review.next_action.title)}</p>${review.next_action.reason ? `<small>${esc(review.next_action.reason)}</small>` : ""}</div>` : ""}`;
  }

  async function loadCourse() {
    const course = selectedCourse();
    if (!course) return null;
    setCourse(course.course_id);
    state.course = await api(withLearner(`/api/courses/${encodeURIComponent(state.courseId)}`));
    return state.course;
  }

  async function hydrateDetail() {
    const course = await loadCourse();
    if (!course) {
      $("#main").innerHTML = emptyState("还没有可查看的课程", "先添加课程，再建立 AI 复盘与 TeleAgent 闭环。", "add-course", "添加课程");
      return;
    }
    $(".page-title").textContent = course.title;
    const courseEyebrow = $(".page-head .eyebrow");
    if (courseEyebrow) courseEyebrow.textContent = `课程 · ${course.subject || "学习"} · ${timeText(course.create_time)}`;
    const crumb = $(".crumb");
    if (crumb) crumb.textContent = `课程 / ${course.title}`;
    $(".page-sub").textContent = `${course.grade || ""}${course.grade ? " · " : ""}${course.duration_text || "时长未记录"} · ${course.scene || "课堂记录"} · 内容已就绪`;
    state.focus = course.review?.payload?.knowledge_points?.[0]?.name || course.title;
    const reading = $("[data-od-id='course-review']");
    const route = ROUTE();
    if (route === "course-knowledge" && course.review?.payload?.structure_version !== 2) {
      course.review = await api(`/api/courses/${encodeURIComponent(course.course_id)}/review`, {
        method: "POST",
        body: JSON.stringify({ learner_id: state.learnerId, force: true }),
      });
    }
    const tabRoute = { "course-detail": "course-detail", "course-knowledge": "course-knowledge", "course-relations": "course-relations", "course-interactions": "course-interactions" }[route] || "course-detail";
    $$(".tabs .tab").forEach((tab) => tab.classList.toggle("active", (tab.getAttribute("href") || "").startsWith(tabRoute)));
    if (reading && route === "course-detail") reading.innerHTML = reviewHtml(course.review, course);
    if (reading && route === "course-detail") reading.insertAdjacentHTML("afterbegin", `<div class="knowledgebook-banner"><span class="ai-orb"><i></i></span><div><strong>课程知识本</strong><small>平台 AI 只依据这堂课的摘要、逐字稿和原始时间点形成内容</small></div><button class="text-link" data-go="course-transcript">查看全部来源</button></div>`);
    if (reading && route === "course-knowledge") {
      const review = course.review?.payload;
      reading.innerHTML = review ? `<div class="reading-block"><span class="ai-label">平台 AI 结构化 · 节点均可回到课程</span><h2>知识脉络</h2>
        <div class="knowledge-map"><div class="map-root"><span>课程主题</span><strong>${esc(course.title)}</strong></div>
        <div class="map-branches">${(review.knowledge_points || []).map((point, index) => `<article class="map-node"><div class="map-node-head"><span>${String(index + 1).padStart(2, "0")}</span>${point.node_type ? `<small>${esc(point.node_type)}</small>` : ""}${point.relation_to_course ? `<i>${esc(point.relation_to_course)}</i>` : ""}</div><h3>${esc(point.name)}</h3><p>${esc(point.explanation)}</p>${(point.children || []).length ? `<ul class="map-children">${point.children.map((child) => `<li>${esc(child)}</li>`).join("")}</ul>` : ""}${point.evidence_quote ? `<blockquote><b>课堂原话</b>${esc(point.evidence_quote)}</blockquote>` : ""}</article>`).join("")}</div></div></div>`
        : `<div class="reading-block review-empty"><span class="ai-label">尚未形成知识结构</span><h2>先生成本课 AI 复盘</h2><p>平台将从课程摘要和逐字稿中提取知识节点与原文依据。</p><button class="btn btn-primary js-generate-review">生成 AI 复盘</button></div>`;
    }
    if (reading && route === "course-relations") {
      reading.innerHTML = `<div class="reading-block"><span class="ai-label">平台 AI 正在分析</span><h2>跨课程关联</h2><p>正在比较当前课程与同一学习者的历史课程……</p></div>`;
      try {
        const relationResult = await api(withLearner(`/api/courses/${encodeURIComponent(course.course_id)}/relations`));
        const relations = relationResult.payload?.links || [];
        reading.innerHTML = `<div class="reading-block"><span class="ai-label">平台 AI · 发现线索，不替代判断</span><h2>跨课程关联</h2><p>${esc(relationResult.payload?.explanation || "关联仅用于找到可能相关的历史课程。")}</p></div>
          <div class="relation-list">${relations.map((item) => `<button class="relation-card js-related-course" data-course-id="${esc(item.course_id)}"><span class="relation-type">${esc(item.relation)}</span><div><h3>${esc(item.title)}</h3><p>${esc(item.reason)}</p><small>${esc((item.shared_concepts || []).join(" · ") || item.confidence || "待核对")}</small></div><span class="relation-open">查看课程 →</span></button>`).join("") || `<div class="reading-block"><h2>暂未发现可靠关联</h2><p>新增更多课程后，平台会继续建立跨课线索。</p></div>`}</div>`;
      } catch (error) { reading.innerHTML = `<div class="error-box">${esc(error.message)}</div>`; }
    }
    if (reading && route === "course-interactions") {
      const allRuns = await api(withLearner("/api/teleagent/runs"));
      const runs = (allRuns.items || []).filter((run) => String(run.course_id) === String(course.course_id));
      reading.innerHTML = `<div class="reading-block"><span class="ai-label">TeleAgent 互动留痕</span><h2>互动结果</h2><p>这里不进行练习，只保存任务状态、结构化结果和对成长档案的影响。</p></div>
        <div class="interaction-list">${runs.map((run) => `<button class="interaction-row js-open-run" data-run-id="${esc(run.run_id)}"><div><strong>${esc(ACTIONS[run.action] || "学习互动")}</strong><small>${esc(timeText(run.created_at))} · ${esc(run.focus)}</small></div><span class="badge ${run.state === "completed" ? "ready" : run.state === "failed" ? "danger" : "pending"}">${esc(stateLabel(run.state))}</span></button>`).join("") || `<div class="reading-block"><h2>还没有互动记录</h2><p>从右侧选择任务发送到 TeleAgent，完成后结果会回到这里。</p></div>`}</div>`;
    }
    $$("[data-od-id='teleagent-task-list'] .task-card").forEach((button) => {
      button.classList.add("js-open-platform-drawer");
      const text = button.textContent;
      button.dataset.action = text.includes("思维导图") ? "mind_map" : text.includes("检测") ? "learning_check" : text.includes("跨课程") ? "cross_course_review" : "course_review";
      button.dataset.courseId = course.course_id;
    });
    const resultNote = $("[data-od-id='teleagent-task-list'] .quote");
    const latest = (state.bootstrap.recent_runs || []).find((run) => String(run.course_id) === String(course.course_id) && run.state === "completed");
    if (resultNote) resultNote.innerHTML = latest
      ? `<strong>最近结果</strong><br>${esc(ACTIONS[latest.action] || "TeleAgent 互动")}已回流成长档案。<br><button class="text-link" data-go="teleagent-result">查看结果</button>`
      : `<strong>尚无回流结果</strong><br>从上方选择任务，在 TeleAgent 完成后会在这里留下记录。`;
    if (resultNote && latest) {
      const archived = Boolean(latest.result?.analysis);
      resultNote.innerHTML = archived
        ? `<strong>最近结果</strong><br>${esc(ACTIONS[latest.action] || "TeleAgent 互动")}已由平台 AI 提炼并进入学习档案。<br><button class="text-link js-open-run" data-run-id="${esc(latest.run_id)}">查看档案结果</button>`
        : `<strong>TeleAgent 会话已生成</strong><br>继续完成交流，结束时发送“结束复盘并回流课迹”，平台才会更新学习档案。<br><button class="text-link js-open-run" data-run-id="${esc(latest.run_id)}">查看当前结果</button>`;
    }
  }

  async function hydrateTranscript() {
    const course = await loadCourse();
    if (!course) return;
    const segments = course.segments || [];
    const crumb = $(".crumb");
    if (crumb) crumb.textContent = `课程 / ${course.title}`;
    $(".page-head .eyebrow").textContent = `${course.subject || "课程"} · 课程文字记录`;
    $(".page-title").textContent = course.title;
    $(".page-sub").textContent = "浏览当前课程保存的文字内容，选择片段后可带到 TeleAgent 继续探讨。";
    const host = $("[data-od-id='transcript']");
    const selection = $("[data-od-id='transcript-selection']");
    if (!host || !selection) return;
    if (!segments.length) {
      host.innerHTML = `<div class="error-box">当前课程没有可显示的文字内容。</div>`;
      selection.innerHTML = `<div class="eyebrow">当前课程</div><h2>${esc(course.title)}</h2><p>没有可带到 TeleAgent 的课程片段。</p>`;
      return;
    }
    host.innerHTML = `<div class="toolbar"><input class="field search transcript-search" placeholder="搜索课程文字" aria-label="搜索课程文字"><span class="badge pending">${segments.length} 段文字</span></div>
      <div class="transcript-list">${segments.map((segment, index) => `<button type="button" class="transcript-row js-transcript-segment${index === 0 ? " is-selected" : ""}" data-index="${index}"><span class="timestamp">段 ${String(index + 1).padStart(2, "0")}</span><strong class="speaker">${esc(segment.speaker)}</strong><p>${esc(segment.content)}</p></button>`).join("")}</div>`;

    const selectSegment = (index) => {
      const segment = segments[index];
      if (!segment) return;
      $$(".js-transcript-segment", host).forEach((row) => row.classList.toggle("is-selected", Number(row.dataset.index) === index));
      state.focus = segment.content;
      selection.innerHTML = `<div class="eyebrow">已选课程文字</div><h2>第 ${index + 1} 段</h2><p>${esc(segment.content)}</p><div class="quote">来源：《${esc(course.title)}》<br>${esc(segment.speaker)} · 课程文字第 ${index + 1} 段</div><div class="actions"><button class="btn btn-primary js-open-platform-drawer" data-action="course_review" data-course-id="${esc(course.course_id)}">和 TeleAgent 聊聊</button></div>`;
    };
    selectSegment(0);
    $$(".js-transcript-segment", host).forEach((row) => row.addEventListener("click", () => selectSegment(Number(row.dataset.index))));
    $(".transcript-search")?.addEventListener("input", (event) => {
      const key = event.target.value.trim().toLowerCase();
      $$(".transcript-row", host).forEach((row) => { row.hidden = !row.textContent.toLowerCase().includes(key); });
    });
  }

  const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  let audioImporting = false;

  function setupAudioDropzone() {
    const card = $$(".upload-card").find((item) => item.textContent.includes("上传音频"));
    if (!card || card.dataset.dropReady) return;
    card.dataset.dropReady = "true";
    card.classList.add("audio-dropzone");
    card.setAttribute("aria-label", "选择或拖入课堂音频");
    card.insertAdjacentHTML("beforeend", `<input class="audio-demo-input" type="file" accept="audio/*,video/*" hidden>`);
    const input = $(".audio-demo-input", card);
    input?.addEventListener("change", () => input.files?.[0] && importDemoAudio(input.files[0]));
    ["dragenter", "dragover"].forEach((name) => card.addEventListener(name, (event) => {
      event.preventDefault(); card.classList.add("is-dragging");
    }));
    ["dragleave", "drop"].forEach((name) => card.addEventListener(name, (event) => {
      event.preventDefault(); card.classList.remove("is-dragging");
    }));
    card.addEventListener("drop", (event) => {
      const file = event.dataTransfer?.files?.[0];
      if (file) importDemoAudio(file);
    });
    const footerCopy = $("#main > p:last-child");
    if (footerCopy) footerCopy.textContent = "导入完成后会形成课程摘要、逐字稿和可以继续复盘的课程记录。";
  }

  function renderAudioProgress(fileName, stage, error = "") {
    const host = $(".upload-grid")?.parentElement;
    if (!host) return;
    let panel = $(".audio-import-progress", host);
    if (!panel) {
      host.insertAdjacentHTML("beforeend", `<section class="card audio-import-progress" aria-live="polite"></section>`);
      panel = $(".audio-import-progress", host);
    }
    const steps = ["读取录音文件", "转写课程内容", "建立课程档案"];
    panel.innerHTML = `<div class="audio-progress-head"><div><span class="eyebrow">正在添加课程</span><h2>${esc(fileName)}</h2></div><strong>${error ? "添加未完成" : stage >= steps.length ? "课程已准备好" : steps[stage]}</strong></div>
      <div class="audio-progress-track">${steps.map((label, index) => `<span class="${index < stage ? "done" : index === stage ? "active" : ""}"><b>${index < stage ? "完成" : index === stage ? "进行中" : "等待"}</b>${label}</span>`).join("")}</div>
      ${error ? `<div class="error-box">${esc(error)}，请重新选择文件。</div>` : `<p>${stage === 0 ? "录音文件已接收，正在读取基础信息。" : stage === 1 ? "正在转写说话内容，并区分不同说话人。" : stage === 2 ? "正在保存课程摘要和逐字稿。" : "即将打开新课程。"}</p>`}`;
    panel.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function importDemoAudio(file) {
    if (!file) return;
    if (audioImporting) return toast("当前课程仍在生成，请等待完成后再添加下一门课", true);
    const supported = /\.(mp3|wav|m4a|aac|flac|mp4|mov)$/i.test(file.name) || /^(audio|video)\//.test(file.type || "");
    if (!supported) return toast("请选择常见音频或视频文件", true);
    const inferredTitle = file.name.replace(/\.(mp3|wav|m4a|aac|flac|mp4|mov)$/i, "").replace(/_/g, " ").trim();
    const titleField = $(".js-audio-title");
    if (titleField && !titleField.value.trim()) titleField.value = inferredTitle;
    audioImporting = true;
    renderAudioProgress(file.name, 0);
    try {
      await wait(650); renderAudioProgress(file.name, 1);
      const course = await api("/api/courses/import-audio-demo", {
        method: "POST", body: JSON.stringify({
          learner_id: state.learnerId,
          file_name: file.name,
          title: titleField?.value.trim() || inferredTitle,
          subject: $(".js-audio-subject")?.value || "",
          duration_range: $(".js-audio-duration")?.value || "under_5",
          speaker_mode: $(".js-audio-speakers")?.value || "2",
        }),
      });
      setCourse(course.course_id);
      renderAudioProgress(file.name, 3);
      toast(`《${course.title}》已加入课程`);
      await wait(900); go("course-detail");
    } catch (error) { renderAudioProgress(file.name, 0, error.message); }
    finally { audioImporting = false; }
  }

  function installImportComposer(source) {
    const host = $(".upload-grid")?.parentElement;
    if (!host) return;
    $(".import-composer")?.remove();
    host.insertAdjacentHTML("beforeend", `<article class="card section import-composer">
      <div class="section-head"><div><div class="eyebrow">文本导入</div><h2>建立课程档案</h2></div><span class="badge pending">保存到个人学习记录</span></div>
      <div class="form-grid"><label>课程名称<input class="field" id="import-title" value="" placeholder="例如：二次函数的图像"></label>
      <label>学科<input class="field" id="import-subject" value="数学"></label><label>场景<input class="field" id="import-scene" value="学校课堂"></label></div>
      <label class="field-label">课程摘要<textarea class="field textarea" id="import-summary" placeholder="已有摘要可直接粘贴"></textarea></label>
      <label class="field-label">课程文字或课堂笔记<textarea class="field textarea transcript-input" id="import-transcript" placeholder="说话人1：……\n说话人2：……"></textarea></label>
      <div class="actions"><button class="btn btn-primary js-import-course">保存并准备课程</button><span class="muted-copy">保存后即可查看摘要、逐字稿，并继续和 TeleAgent 探讨。</span></div></article>`);
    $(".import-composer")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function importCourse(button) {
    const payload = {
      learner_id: state.learnerId,
      title: $("#import-title")?.value.trim(), subject: $("#import-subject")?.value.trim() || "课程",
      scene: $("#import-scene")?.value.trim() || "课堂记录", summary: $("#import-summary")?.value.trim(),
      transcript: $("#import-transcript")?.value.trim(), source_type: "text_demo",
    };
    if (!payload.title || !payload.transcript) return toast("请填写课程名称和逐字稿", true);
    button.disabled = true; button.textContent = "正在保存…";
    try {
      const course = await api("/api/courses/import", { method: "POST", body: JSON.stringify(payload) });
      setCourse(course.course_id); toast("课程已保存，正在建立内容结构"); go("course-processing");
      setTimeout(() => go("course-detail"), 1700);
    } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "保存并准备课程"; }
  }

  async function generateReview(button) {
    if (!state.courseId) return;
    button.disabled = true; button.textContent = "正在生成复盘…";
    try {
      const result = await api(`/api/courses/${encodeURIComponent(state.courseId)}/review`, {
        method: "POST", body: JSON.stringify({ learner_id: state.learnerId }),
      });
      state.course.review = result;
      state.focus = result.payload?.knowledge_points?.[0]?.name || state.course.title;
      await hydrateDetail();
      toast("AI 复盘已生成并留痕");
    } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "重新生成"; }
  }

  function openDrawer(trigger) {
    const courseId = trigger?.dataset.courseId;
    if (courseId) setCourse(courseId);
    state.action = trigger?.dataset.action || inferAction(trigger?.textContent || "") || state.action;
    const course = selectedCourse();
    if (!course && state.action !== "study_plan") return toast("请先选择或添加一堂课程", true);
    const scrim = $(".drawer-scrim");
    scrim?.classList.add("open"); document.body.style.overflow = "hidden";
    const drawerTitle = $("#drawer-title", scrim);
    if (drawerTitle) drawerTitle.textContent = "和 TeleAgent 聊聊";
    const drawerAction = $(".js-send-now", scrim);
    if (drawerAction) drawerAction.textContent = "复制本次课程 Prompt 并打开 TeleAgent";
    const quote = $(".drawer-section .quote", scrim);
    if (quote) quote.innerHTML = `<strong>《${esc(course?.title || "近期成长状态")}》</strong><br><small>当前学习者：${esc(state.bootstrap.learner.display_name)} · 重点：${esc(state.focus)}</small>`;
    const drawerNotes = $$(".drawer-section .quote", scrim);
    if (drawerNotes.length > 1) drawerNotes.at(-1).innerHTML = `<strong>本次探讨会留在 TeleAgent</strong><br><small>课程内容已经准备好。打开 TeleAgent 后新建任务、粘贴发送即可开始。</small>`;
    $$(".radio-card", scrim).forEach((radio) => {
      radio.dataset.action = radio.dataset.action || inferAction(radio.textContent);
      radio.classList.toggle("active", radio.dataset.action === state.action);
    });
    syncDrawerActionUI(scrim);
  }

  const TASK_PREVIEWS = {
    course_review: {
      title: "从你最想弄懂的问题开始",
      copy: "TeleAgent 会先读取课程主线与原文，再根据你的回答追问；结束后保留这次复盘的关键对话。",
    },
    mind_map: {
      title: "把概念、例题和易错点连成一张图",
      copy: "TeleAgent 会生成不超过三层的思维导图，重要节点带上课堂原文或时间点。",
    },
    learning_check: {
      title: "记录答案，也记录你是怎么想的",
      copy: "TeleAgent 会一次问一个问题，保留回答、提示与自我纠正；结束后再回到课迹整理。",
    },
    cross_course_review: {
      title: "把这堂课和以前学过的内容连起来",
      copy: "TeleAgent 会查找历史课程中的相关讲解，说明它们的联系、差异与来源。",
    },
  };

  function syncDrawerActionUI(scrim = $(".drawer-scrim")) {
    if (!scrim) return;
    const preview = TASK_PREVIEWS[state.action] || TASK_PREVIEWS.course_review;
    const options = $(".js-action-options", scrim);
    if (options) options.hidden = state.action !== "learning_check";
    const title = $(".js-task-preview-title", scrim);
    const copy = $(".js-task-preview-copy", scrim);
    if (title) title.textContent = preview.title;
    if (copy) copy.textContent = preview.copy;
    $$(".radio-card", scrim).forEach((radio) => radio.classList.toggle("active", radio.dataset.action === state.action));
  }

  function collectTaskParameters() {
    if (state.action !== "learning_check") return {};
    return {
      question_count: Number($(".js-question-count")?.value || 3),
      difficulty: $(".js-difficulty")?.value || "跟随课堂",
    };
  }

  function inferAction(text) {
    return text.includes("思维导图") ? "mind_map" : text.includes("检测") || text.includes("复测") || text.includes("验证") ? "learning_check"
      : text.includes("跨课") || text.includes("跨课程") ? "cross_course_review" : text.includes("建议") || text.includes("计划") ? "study_plan" : "course_review";
  }

  async function submitTeleAgent(button) {
    const course = selectedCourse();
    if (!course) return toast("请先选择一堂课程", true);
    button.disabled = true; button.textContent = "正在准备本课内容…";
    try {
      const run = await api("/api/teleagent/runs", { method: "POST", body: JSON.stringify({
        learner_id: state.learnerId, course_id: course.course_id, action: state.action,
        focus: state.focus || course.title, parameters: collectTaskParameters(), delivery_mode: "copy",
      }) });
      state.runId = run.run_id; localStorage.setItem(KEY.run, run.run_id);
      state.handoffPrompt = run.prompt || "";
      sessionStorage.setItem(KEY.prompt, state.handoffPrompt);
      await copyText(state.handoffPrompt);
      $(".drawer-scrim")?.classList.remove("open"); document.body.style.overflow = "";
      go("teleagent-delivery");
      try {
        await api(`/api/teleagent/runs/${encodeURIComponent(run.run_id)}/start`, { method: "POST", body: "{}" });
        await api("/api/teleagent/focus", { method: "POST", body: "{}" });
        toast("本课内容已复制；请在 TeleAgent 新建任务后粘贴发送");
      } catch (focusError) { toast(`本课内容已复制，请手动打开 TeleAgent：${focusError.message}`, true); }
    } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "复制本次课程 Prompt 并打开 TeleAgent"; }
  }

  const stateLabel = (runState) => ({
    prompt_ready: "待开始", submitting: "正在开始", sent: "已打开", running: "交流中", awaiting_result: "等待整理",
    processing_result: "正在整理", completed: "已整理", failed: "未完成", demo_ready: "待开始",
  })[runState] || runState || "待开始";

  async function hydrateDelivery() {
    const title = $(".page-title");
    const sub = $(".page-sub");
    const eyebrow = $(".page-head .eyebrow");
    const crumb = $(".crumb");
    if (eyebrow) eyebrow.textContent = "本次课程探讨";
    if (crumb) crumb.textContent = "课程 / 和 TeleAgent 聊聊";
    if (title) title.textContent = "和 TeleAgent 继续探讨";
    if (sub) sub.textContent = "本课内容已经准备好；聊完后，学习发现会回到个人长期记录。";
    if (!state.runId) {
      const grid = $("#main .grid.grid-2");
      if (grid) grid.innerHTML = `<article class="card empty-state"><span class="empty-mark">课</span><h2>还没有正在进行的探讨</h2><p>先选择一堂课程，再决定要复盘、提问还是做一次学习检测。</p><button class="btn btn-primary" data-go="courses">选择课程</button></article>`;
      return;
    }
    const render = (run) => {
      const grid = $("#main .grid.grid-2");
      if (!grid) return;
      const completed = run.state === "completed";
      const prompt = state.handoffPrompt || sessionStorage.getItem(KEY.prompt) || "";
      const processing = run.state === "processing_result" || run.state === "awaiting_result";
      grid.innerHTML = `<article class="card delivery-card handoff-card"><div class="evidence-chain">
        <span class="chain-step done"><b>1</b>本课已准备</span><span class="chain-arrow">→</span>
        <span class="chain-step ${run.state === "prompt_ready" ? "active" : "done"}"><b>2</b>打开 TeleAgent</span><span class="chain-arrow">→</span>
        <span class="chain-step ${run.state === "running" ? "active" : processing || completed ? "done" : "pending"}"><b>3</b>完成探讨</span><span class="chain-arrow">→</span>
        <span class="chain-step ${completed ? "done" : processing ? "active" : "pending"}"><b>4</b>形成学习记录</span></div>
        <span class="badge ${run.state === "failed" ? "danger" : "ready"}">${esc(stateLabel(run.state))}</span>
        <h2>${completed ? "这次探讨已经整理好了" : run.state === "processing_result" ? "正在把对话变成学习记录" : "去 TeleAgent 继续这次探讨"}</h2>
        <p>《${esc(run.course_title)}》 · ${esc(ACTIONS[run.action] || "课程探讨")}</p>
        ${run.error ? `<div class="error-box">${esc(run.error)}</div>` : ""}
        ${completed ? `<div class="handoff-complete"><strong>个人学习记录已更新</strong><span>这次提问、理解变化和下一步建议已经进入长期学习档案。</span></div>` : `<ol class="handoff-steps"><li><b>1</b><span><strong>在 TeleAgent 新建任务</strong><small>新会话会出现在 TeleAgent 的历史记录中。</small></span></li><li><b>2</b><span><strong>粘贴刚刚复制的本课内容</strong><small>发送后即可围绕这堂课提问、复盘或自测。</small></span></li><li><b>3</b><span><strong>聊完后发送“结束复盘并回流课迹”</strong><small>稍后回到这里查看本次探讨带来的学习发现。</small></span></li></ol>`}
        ${prompt && !completed ? `<label class="prompt-preview-label">本次课程 Prompt<textarea class="prompt-preview" readonly>${esc(prompt)}</textarea></label>` : ""}
        <div class="actions">${!completed ? `<button class="btn btn-primary js-copy-open-teleagent">复制本次课程 Prompt 并打开 TeleAgent</button><button class="btn btn-secondary js-copy-prompt">仅复制 Prompt</button>` : `<button class="btn btn-primary" data-go="teleagent-result">查看本次学习发现</button>`}<button class="btn btn-ghost" data-go="course-detail">回到课程</button></div></article>
        <aside class="card handoff-boundary"><div class="eyebrow">云续成长迹</div><h2>聊完以后，平台继续记得</h2><p>这次提问、理解变化和仍待解决的问题，会成为下一次学习可以继续使用的记录。</p><div class="quote"><strong>不是堆积聊天记录</strong><br>只整理对以后学习真正有帮助的内容，并保留它来自哪堂课、哪次探讨。</div></aside>`;
    };
    const poll = async (count = 0) => {
      try {
        const run = await api(`/api/teleagent/runs/${encodeURIComponent(state.runId)}`); render(run);
        if (!["completed", "failed"].includes(run.state) && count < 360 && ROUTE() === "teleagent-delivery") setTimeout(() => poll(count + 1), 4000);
      } catch (error) {
        const grid = $("#main .grid.grid-2");
        if (grid) grid.innerHTML = `<article class="card empty-state"><span class="empty-mark">课</span><h2>这次探讨已经不在当前记录中</h2><p>回到课程重新开始即可，已有课程内容不会受到影响。</p><button class="btn btn-primary" data-go="courses">重新选择课程</button></article>`;
      }
    };
    poll();
  }

  async function hydrateResult() {
    if (!state.runId) return;
    try {
      const run = await api(`/api/teleagent/runs/${encodeURIComponent(state.runId)}`);
      const result = run.result || {};
      $(".page-title").textContent = `${ACTIONS[run.action] || "互动"}结果`;
      $(".page-sub").textContent = `来源：《${run.course_title || "课程"}》 · ${stateLabel(run.state)} · 结果已归属 ${state.bootstrap.learner.display_name}`;
      const grid = $("#main .grid.grid-2");
      if (!grid) return;
      const questions = result.questions || [];
      const analysis = result.analysis || null;
      const correct = questions.filter((item) => item.correct).length;
      if (analysis) {
        const insights = analysis.insights || [];
        grid.innerHTML = `<article class="card dialogue-result"><div class="ai-analysis-head"><span class="ai-orb"><i></i></span><div><div class="eyebrow">课迹 AI · 整段对话分析</div><h2>这次对话发生了什么</h2></div><span class="badge ready">AI 已提炼</span></div>
          ${analysis.episode_summary ? `<p class="analysis-lead">${esc(analysis.episode_summary)}</p>` : ""}
          <div class="dialogue-facts"><div><span>学生提出</span><strong>${esc((analysis.questions_asked || []).length)} 个问题</strong></div><div><span>涉及</span><strong>${esc((analysis.topics || []).length)} 个知识点</strong></div><div><span>提炼</span><strong>${esc(insights.length)} 条学习发现</strong></div></div>
          <div class="insight-stack">${insights.map((item, index) => `<article class="insight-card"><span class="insight-index">${String(index + 1).padStart(2, "0")}</span><div><div class="meta-row"><span>${esc(insightTypeLabel(item.type))} · ${esc(item.knowledge_point || run.focus)}</span><span class="confidence">置信度 ${Math.round(Number(item.confidence || 0) * 100)}%</span></div><h3>${esc(item.content)}</h3><p>${esc(verdictCopy(item))}</p><button class="text-link js-insight-evidence" data-turns="${esc((item.evidence_turn_indexes || []).join(","))}">查看对话与课程依据</button></div></article>`).join("") || `<p>本次只完成了原始对话留痕，尚无可靠洞察。</p>`}</div></article>
          <aside class="card"><div class="eyebrow">对长期档案的影响</div><h2>不是一句“答对了”</h2>${(result.changes || []).map((change) => `<div class="state-change"><strong>${esc(change.knowledge_point)}</strong><div class="trace"><span class="trace-node">${esc(change.previous)}</span><span class="trace-line"></span><span class="trace-node">${esc(change.level)}</span></div><small>${esc(change.reason)}</small></div>`).join("") || `<p>证据不足，当前状态保持不变并等待下一次验证。</p>`}
          ${(result.plans || []).map((plan) => `<div class="quote"><strong>下一步验证</strong><br>${esc(plan.title)} · 约 ${esc(plan.minutes)} 分钟</div>`).join("")}
          <div class="memory-impact"><span>已写入</span><strong>${esc((analysis.memory_candidates || []).length)} 条记忆候选</strong><small>候选不会自动成为永久事实，可在学习档案中查看依据。</small></div>
          <div class="actions"><button class="btn btn-primary" data-go="growth-overview">查看学习档案</button></div></aside>`;
        return;
      }
      grid.innerHTML = `<article class="card"><div class="result-score"><strong>${questions.length ? `${correct} / ${questions.length}` : "已完成"}</strong><span>${questions.length ? "答对" : "互动结果"}</span></div>
        <p>${esc(result.summary || "TeleAgent 已完成处理，结构化结果等待进一步确认。")}</p>
        ${questions.map((question, index) => `<div class="answer"><div class="meta-row"><span>第 ${index + 1} 题 · ${esc(question.knowledge_point || run.focus)}</span><strong class="${question.correct ? "correct" : "wrong"}">${question.correct ? "回答正确" : "需要巩固"}</strong></div>
          <h3>${esc(question.stem)}</h3><div class="answer-grid"><div class="answer-box"><strong>${esc(state.bootstrap.learner.display_name)}的答案</strong><span>${esc(question.student_answer)}</span></div>
          <div class="answer-box"><strong>参考答案</strong><span>${esc(question.correct_answer)}</span></div></div>
          <div class="quote">${esc(question.explanation || "")}<small class="evidence-caption">课程依据：${esc(question.evidence || run.course_title)}</small></div></div>`).join("")}</article>
        <aside class="card"><div class="eyebrow">可信回流</div><h2>成长状态如何变化</h2>
          ${(result.changes || []).map((change) => `<div class="state-change"><strong>${esc(change.knowledge_point)}</strong><div class="trace"><span class="trace-node">${esc(change.previous)}</span><span class="trace-line"></span><span class="trace-node">${esc(change.level)}</span></div><small>${esc(change.reason)}</small></div>`).join("") || `<p>本次结果未改变掌握状态。</p>`}
          ${(result.plans || []).map((plan) => `<div class="quote"><strong>已生成下一步</strong><br>${esc(plan.title)} · 约 ${esc(plan.minutes)} 分钟</div>`).join("")}
          <div class="actions"><button class="btn btn-primary" data-go="learning-plan">查看长期计划</button></div></aside>`;
    } catch (error) { toast(error.message, true); }
  }

  async function hydrateGrowth(route) {
    if (["growth-timeline", "learning-plan"].includes(route)) { go("growth-overview"); return; }
    const [growth, runData, chatData] = await Promise.all([
      api(withLearner("/api/growth")),
      api(withLearner("/api/teleagent/runs")),
      api(withLearner("/api/ai/archive-chat")),
    ]);
    const runs = runData.items || [];
    const crumb = $(".crumb");
    if (crumb) crumb.textContent = "学习成长 · TeleAgent 回流与长期记忆";
    const pageHead = $(".page-head");
    if (pageHead) {
      $(".js-open-platform-drawer", pageHead)?.remove();
      $(".page-title", pageHead).textContent = route === "growth-profile" ? "长期记忆" : route === "growth-knowledge" ? "问课迹 AI" : "学习回流";
      $(".page-sub", pageHead).textContent = route === "growth-profile"
        ? "查看平台从课程与 TeleAgent 对话中长期保留了什么，以及每条记忆的来源。"
        : route === "growth-knowledge"
          ? "让平台 AI 基于个人长期学习档案，完成期末回顾、薄弱点分析和复习建议。"
          : "课程进入 TeleAgent，结束后回流；平台 AI 将关键对话整理为可持续使用的学习记录。";
    }
    const routeTab = { "growth-overview": "growth-overview", "growth-knowledge": "growth-knowledge", "growth-profile": "growth-profile" }[route];
    $$(".tabs .tab").forEach((tab) => tab.classList.toggle("active", (tab.getAttribute("href") || "").startsWith(routeTab)));
    const tabs = $(".tabs");
    let node = tabs?.nextElementSibling; while (node) { const next = node.nextElementSibling; node.remove(); node = next; }

    if (route === "growth-overview") {
      const insights = growth.dialogue_insights || [];
      const runCards = runs.slice(0, 8).map((run) => {
        const analyzed = Boolean(run.result?.analysis);
        const returned = analyzed || run.state === "completed";
        const processing = ["processing_result", "awaiting_result"].includes(run.state);
        const active = ["sent", "running", "submitting"].includes(run.state);
        const status = analyzed ? "已整理" : returned || processing ? "正在整理" : active ? "交流中" : "待开始";
        const relatedInsights = insights.filter((item) => item.run_id === run.run_id);
        const description = analyzed ? esc(run.result.summary || `已形成 ${relatedInsights.length} 条学习发现`)
          : processing || returned ? "对话已经回来，正在整理问题、理解变化和下一步。"
            : active ? "探讨结束后，在 TeleAgent 发送“结束复盘并回流课迹”。" : "重新从课程页开始这次探讨。";
        return `<article class="return-card ${analyzed ? "is-complete" : active || processing ? "is-active" : ""}"><div class="return-state"><span></span>${esc(status)}</div><div><div class="meta-row"><span>${esc(run.course_title || "学习互动")}</span><span>${esc(timeText(run.updated_at))}</span></div><h3>${esc(ACTIONS[run.action] || "课程互动")} · ${esc(run.focus || "本课内容")}</h3><p>${description}</p><div class="actions">${analyzed ? `<button class="btn btn-secondary js-open-run" data-run-id="${esc(run.run_id)}">查看本次学习发现</button>` : active ? `<button class="btn btn-secondary js-focus-teleagent">回到 TeleAgent 继续</button>` : processing ? `<span class="gentle-status">正在为你整理，请稍候</span>` : `<button class="btn btn-ghost js-start-from-growth">重新选择课程</button>`}</div></div></article>`;
      }).join("");
      tabs?.insertAdjacentHTML("afterend", `<section class="return-flow" aria-label="学习回流的四个步骤"><div class="flow-step"><b>01</b><span><strong>选择课程</strong><small>带上课程原文</small></span></div><div class="flow-step"><b>02</b><span><strong>在 TeleAgent 探讨</strong><small>提问、复盘或自测</small></span></div><div class="flow-step"><b>03</b><span><strong>结束并回流</strong><small>带回关键对话</small></span></div><div class="flow-step"><b>04</b><span><strong>形成长期记录</strong><small>留给下一次学习</small></span></div></section>
        <section class="return-layout"><div><div class="section-head"><div><div class="eyebrow">最近学习互动</div><h2>每次 TeleAgent 对话现在走到哪一步</h2></div><button class="btn btn-primary js-start-from-growth">选择课程开始新互动</button></div><div class="return-list">${runCards || `<div class="card archive-empty"><strong>还没有 TeleAgent 学习互动</strong><p>先从课程管理选择一门课，发送到 TeleAgent。</p></div>`}</div></div>
        <aside class="memory-output"><span class="ai-orb large"><i></i></span><div class="eyebrow">云续成长迹</div><h2>聊过的内容，会成为下一次学习的起点</h2><ul><li><strong>你主动问过什么</strong><span>保留真实问题和相关课程</span></li><li><strong>哪里需要过提示</strong><span>记录理解过程，而不只看对错</span></li><li><strong>还有什么没弄懂</strong><span>留到下一次继续验证</span></li><li><strong>接下来先做什么</strong><span>形成适合你的复习建议</span></li></ul><div class="actions"><button class="btn btn-primary" data-go="growth-profile">查看长期记忆</button><button class="btn btn-ghost" data-go="growth-knowledge">问问课迹 AI</button></div></aside></section>`);
    }
    if (route === "growth-profile") {
      const memories = growth.learning_memories || [];
      const weak = (growth.mastery || []).filter((item) => item.level === "待巩固" || item.level === "待验证").slice(0, 6);
      tabs?.insertAdjacentHTML("afterend", `<section class="memory-explainer"><div><div class="eyebrow">个性化长期记忆</div><h2>记住真实学习过程，也记住每个结论从哪里来</h2><p>课程内容和每次探讨都会留下依据。平台只保留对以后学习有帮助的信息，例如主动问过的问题、需要提示的地方和仍待验证的知识点。</p></div><div class="memory-layers"><span><b>学过什么</b>课程与课堂原文</span><span><b>聊过什么</b>问题与理解变化</span><span><b>接着做什么</b>薄弱点与下一步</span></div></section>
        <section class="memory-dashboard"><div class="card"><div class="section-head"><div><div class="eyebrow">当前需要关注</div><h2>平台在下一次回答中会优先带上的薄弱点</h2></div><span class="ledger-count small">${weak.length}<small>个待关注点</small></span></div><div class="weak-list">${weak.map((item) => `<article><span class="badge pending">${esc(item.level)}</span><div><strong>${esc(item.knowledge_point)}</strong><p>${esc(item.last_reason || "仍需要新的学习证据")}</p><small>${esc(item.evidence_count)} 条依据 · ${esc(timeText(item.updated_at))}</small></div></article>`).join("") || `<p class="muted-copy">暂时没有标记为薄弱的知识点，继续通过对话和作答积累证据。</p>`}</div></div>
        <div class="memory-list">${memories.map((item) => `<article class="memory-card"><div class="memory-card-head"><span class="memory-kind">${esc(memoryTypeLabel(item.memory_type))}</span><span class="badge ${item.status === "active" ? "ready" : "pending"}">${Number(item.evidence_count || 0) >= 2 ? "已被多次互动验证" : item.status === "active" ? "已形成长期记忆" : "一次记录，待验证"}</span></div><h3>${esc(item.title || item.knowledge_point || "学习发现")}</h3><p>${esc(item.content)}</p><div class="memory-meta"><span>${esc(item.knowledge_point || "跨课程")}</span><span>${esc(item.evidence_count || 1)} 次互动来源</span><span>可信度 ${Math.round(Number(item.confidence || 0) * 100)}%</span><span>${item.vector_status === "indexed" ? "可被课迹 AI 检索" : "正在进入记忆检索"}</span></div><button class="text-link js-insight-evidence" data-run-id="${esc(item.source_run_id)}">查看来源对话</button></article>`).join("") || `<div class="card archive-empty"><strong>还没有长期记忆</strong><p>在 TeleAgent 中完成一次互动并回流后，平台 AI 会把可复用的学习事实放在这里。</p></div>`}</div></section>`);
    }
    if (route === "growth-knowledge") {
      const messages = chatData.items || [];
      const welcome = messages.length ? "" : `<div class="chat-welcome"><span class="chat-ai-mark">课迹 AI</span><h2>可以从你的长期学习记录开始聊</h2><p>试着回顾近期薄弱点、准备期末复习，或者问问某个学习判断来自哪一次课程。</p></div>`;
      tabs?.insertAdjacentHTML("afterend", `<section class="archive-chat-shell"><aside class="chat-context"><div class="eyebrow">我的学习积累</div><div class="context-stat"><strong>${growth.learning_memories?.length || 0}</strong><span>条长期记忆</span></div><div class="context-stat"><strong>${growth.mastery?.length || 0}</strong><span>个持续关注点</span></div><div class="context-stat"><strong>${growth.course_count || 0}</strong><span>堂课程记录</span></div><p>课迹 AI 会结合你过去的课程和探讨回答，并在重要结论旁标出来源。</p></aside><div class="archive-chat"><div class="archive-chat-toolbar"><span>当前对话</span><button class="text-link js-clear-archive-chat" type="button" ${messages.length ? "" : "disabled"}>清空聊天记录</button></div><div class="chat-messages" aria-live="polite">${welcome}${messages.map((item) => `<article class="chat-message ${item.role === "user" ? "from-user" : "from-ai"}">${item.role === "assistant" ? `<span class="chat-ai-mark small">AI</span>` : ""}<div><small>${item.role === "user" ? "我" : "课迹 AI"}</small><p>${esc(item.content)}</p>${(item.evidence || []).map((evidence) => `<button class="evidence-chip js-insight-evidence" data-run-id="${esc(evidence.source_run_id)}">来自 · ${esc(evidence.title || evidence.knowledge_point || "学习记录")}</button>`).join("")}</div></article>`).join("")}</div><div class="prompt-starters"><button class="js-prompt-starter">为期末考试做一次整体回顾</button><button class="js-prompt-starter">我最近最薄弱的知识点是什么？</button><button class="js-prompt-starter">哪些问题我经常需要提示？</button></div><form class="archive-chat-composer"><label for="archive-question">想从自己的学习记录中了解什么？</label><textarea id="archive-question" class="textarea" rows="2" placeholder="例如：结合最近三堂数学课，我期末前应该先复习什么？"></textarea><button class="btn btn-primary js-ask-archive" type="submit">问问课迹 AI</button></form></div></section>`);
      requestAnimationFrame(() => { const host = $(".chat-messages"); if (host) host.scrollTop = host.scrollHeight; });
    }
  }

  function insightTypeLabel(type) {
    return ({ misconception: "发现误区", understanding: "形成理解", question: "真实提问", strategy: "学习策略", self_correction: "自我纠正", needs_validation: "仍需验证", observation: "学习发现" })[type] || "学习发现";
  }

  function insightSymbol(type) {
    return ({ misconception: "!", understanding: "✓", question: "?", strategy: "↗", self_correction: "↺", needs_validation: "…" })[type] || "·";
  }

  function memoryTypeLabel(type) {
    return ({ episodic: "学习经历", semantic: "知识理解", preference: "方式偏好", plan_reflection: "自我记录" })[type] || "学习记忆";
  }

  function verdictCopy(item) {
    const verdict = item.verdict || "uncertain";
    const help = item.assistance_level || "unknown";
    if (verdict === "incorrect") return "当前证据显示存在理解偏差，需要回到原文并再次验证。";
    if (verdict === "partial") return help === "none" ? "已经形成部分理解，仍缺少完整解释。" : "在提示后形成部分理解，尚不能视为独立完成。";
    if (verdict === "correct") return help === "none" || help === "independent" ? "本次能够独立完成，仍由后续证据决定是否稳定。" : "本次在提示后完成，建议再做一次无提示验证。";
    return "证据不足，平台保留为待验证，不强行判断。";
  }

  async function askArchive(button) {
    const input = $("#archive-question");
    const host = $(".chat-messages");
    const question = input?.value.trim();
    if (!question) return toast("请先输入想了解的问题", true);
    if (host) {
      $(".chat-welcome", host)?.remove();
      host.insertAdjacentHTML("beforeend", `<article class="chat-message from-user"><div><small>我</small><p>${esc(question)}</p></div></article><article class="chat-message from-ai is-thinking"><span class="chat-ai-mark small">AI</span><div><small>课迹 AI</small><p>正在回顾相关课程和长期学习记录…</p></div></article>`);
      host.scrollTop = host.scrollHeight;
    }
    input.value = "";
    button.disabled = true; button.textContent = "正在查找依据…";
    try {
      const result = await api("/api/ai/archive-query", { method: "POST", body: JSON.stringify({ learner_id: state.learnerId, question }) });
      const payload = result.payload || {};
      $(".chat-message.is-thinking", host)?.remove();
      const meta = payload.retrieval_meta || {};
      host?.insertAdjacentHTML("beforeend", `<article class="chat-message from-ai"><span class="chat-ai-mark small">AI</span><div><small>课迹 AI · 结合你的长期学习记录</small><p>${esc(payload.answer || "当前学习记录中还没有足够依据形成结论。")}</p>${(payload.evidence || []).map((item) => `<button class="evidence-chip js-insight-evidence" data-run-id="${esc(item.source_run_id)}">来自 · ${esc(item.title || item.knowledge_point || "学习记录")}</button>`).join("")}<div class="ai-next"><strong>建议下一步</strong>${esc(payload.next_action || "继续通过课程与 TeleAgent 探讨积累学习线索")}</div><p class="answer-boundary">${esc(payload.boundary || "回答只依据当前学习记录，重要结论仍建议在后续学习中验证。")}</p></div></article>`);
      if (host) host.scrollTop = host.scrollHeight;
    } catch (error) {
      $(".chat-message.is-thinking", host)?.remove();
      host?.insertAdjacentHTML("beforeend", `<div class="error-box">${esc(error.message)}</div>`);
    } finally { button.disabled = false; button.textContent = "问问课迹 AI"; }
  }

  async function refreshGrowth(button) {
    button.disabled = true; button.textContent = "正在汇总证据…";
    try {
      await api("/api/growth/refresh", { method: "POST", body: JSON.stringify({ learner_id: state.learnerId }) });
      toast("阶段总结已刷新"); location.reload();
    } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "刷新阶段总结"; }
  }

  async function generatePlan(button) {
    button.disabled = true; button.textContent = "平台 AI 正在规划…";
    try {
      await api("/api/growth/plans/generate", { method: "POST", body: JSON.stringify({ learner_id: state.learnerId }) });
      toast("学习计划已生成并写入成长档案"); go("learning-plan"); if (ROUTE() === "learning-plan") location.reload();
    } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "平台 AI 生成计划"; }
  }

  function completePlan(button) {
    if (button.closest(".plan-card")?.querySelector(".plan-reflection")) return;
    button.insertAdjacentHTML("afterend", `<div class="plan-reflection"><label>完成后的感受<textarea class="field textarea" placeholder="例如：符号关系更清晰，但还需要下一次作答验证。">已完成复习，但还需要下一次题目验证</textarea></label><div class="actions"><button class="btn btn-primary js-confirm-plan" data-plan-id="${esc(button.dataset.planId)}">保存完成记录</button><button class="btn btn-ghost js-cancel-plan">暂不记录</button></div></div>`);
    button.hidden = true;
  }

  async function saveCompletedPlan(button) {
    const reflection = button.closest(".plan-reflection")?.querySelector("textarea")?.value.trim() || "";
    button.disabled = true; button.textContent = "正在写入成长档案…";
    try {
      await api(`/api/growth/plans/${encodeURIComponent(button.dataset.planId)}/complete`, { method: "POST", body: JSON.stringify({ learner_id: state.learnerId, reflection }) });
      await api("/api/growth/refresh", { method: "POST", body: JSON.stringify({ learner_id: state.learnerId }) });
      toast("完成记录已写入；掌握状态仍等待客观作答验证"); location.reload();
    } catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "保存完成记录"; }
  }

  function installEvents() {
    document.addEventListener("click", (event) => {
      const view = event.target.closest(".js-view-course");
      if (view) { event.preventDefault(); setCourse(view.dataset.courseId); go("course-detail"); return; }
      const related = event.target.closest(".js-related-course");
      if (related) { event.preventDefault(); setCourse(related.dataset.courseId); go("course-detail"); return; }
      const runLink = event.target.closest(".js-open-run");
      if (runLink) { event.preventDefault(); state.runId = runLink.dataset.runId; localStorage.setItem(KEY.run, state.runId); go("teleagent-result"); return; }
      const route = event.target.closest("[data-go]");
      if (route) { event.preventDefault(); go(route.dataset.go); return; }
      const source = event.target.closest(".js-demo-upload");
      if (source) {
        event.preventDefault(); event.stopImmediatePropagation();
        if (source.textContent.includes("上传音频")) $(".audio-demo-input", source)?.click();
        else installImportComposer(source.textContent);
        return;
      }
      const importButton = event.target.closest(".js-import-course");
      if (importButton) { event.preventDefault(); importCourse(importButton); return; }
      const review = event.target.closest(".js-generate-review");
      if (review) { event.preventDefault(); generateReview(review); return; }
      const radio = event.target.closest(".radio-card");
      if (radio) {
        state.action = radio.dataset.action || inferAction(radio.textContent);
        syncDrawerActionUI(radio.closest(".drawer-scrim"));
      }
      const drawerButton = event.target.closest(".js-open-platform-drawer");
      if (drawerButton) { event.preventDefault(); event.stopImmediatePropagation(); openDrawer(drawerButton); return; }
      const send = event.target.closest(".js-send-now");
      if (send) { event.preventDefault(); event.stopImmediatePropagation(); submitTeleAgent(send); return; }
      const copyPrompt = event.target.closest(".js-copy-prompt");
      if (copyPrompt) { event.preventDefault(); copyPrompt.disabled = true; copyText(state.handoffPrompt || sessionStorage.getItem(KEY.prompt)).then(() => toast("Prompt 已复制")).catch((error) => toast(error.message, true)).finally(() => { copyPrompt.disabled = false; }); return; }
      const copyOpen = event.target.closest(".js-copy-open-teleagent");
      if (copyOpen) { event.preventDefault(); copyOpen.disabled = true; Promise.all([copyText(state.handoffPrompt || sessionStorage.getItem(KEY.prompt)), api(`/api/teleagent/runs/${encodeURIComponent(state.runId)}/start`, { method: "POST", body: "{}" }), api("/api/teleagent/focus", { method: "POST", body: "{}" })]).then(() => toast("本课内容已复制；请在 TeleAgent 新建任务后粘贴发送")).catch((error) => toast(error.message, true)).finally(() => { copyOpen.disabled = false; }); return; }
      const refresh = event.target.closest(".js-refresh-growth");
      if (refresh) { event.preventDefault(); refreshGrowth(refresh); return; }
      const askArchiveButton = event.target.closest(".js-ask-archive");
      if (askArchiveButton) { event.preventDefault(); askArchive(askArchiveButton); return; }
      const clearArchive = event.target.closest(".js-clear-archive-chat");
      if (clearArchive) {
        event.preventDefault();
        if (!window.confirm("清空当前聊天记录？课程和长期记忆会继续保留。")) return;
        clearArchive.disabled = true;
        api("/api/ai/archive-chat/clear", { method: "POST", body: JSON.stringify({ learner_id: state.learnerId }) })
          .then(() => {
            const host = $(".chat-messages");
            if (host) host.innerHTML = `<div class="chat-welcome"><span class="chat-ai-mark">课迹 AI</span><h2>可以从你的长期学习记录开始聊</h2><p>试着回顾近期薄弱点、准备期末复习，或者问问某个学习判断来自哪一次课程。</p></div>`;
            toast("当前聊天记录已清空");
          })
          .catch((error) => { clearArchive.disabled = false; toast(error.message, true); });
        return;
      }
      const promptStarter = event.target.closest(".js-prompt-starter");
      if (promptStarter) { event.preventDefault(); const input = $("#archive-question"); if (input) { input.value = promptStarter.textContent.trim(); input.focus(); } return; }
      const focusTeleAgent = event.target.closest(".js-focus-teleagent");
      if (focusTeleAgent) { event.preventDefault(); focusTeleAgent.disabled = true; api("/api/teleagent/focus", { method: "POST", body: "{}" }).then(() => toast("已切换到 TeleAgent，请结束对话后发送回流指令")).catch((error) => toast(error.message, true)).finally(() => { focusTeleAgent.disabled = false; }); return; }
      const startGrowth = event.target.closest(".js-start-from-growth");
      if (startGrowth) { event.preventDefault(); go("courses"); toast("选择一门课程，再点击“和 TeleAgent 聊聊”"); return; }
      const insightEvidence = event.target.closest(".js-insight-evidence");
      if (insightEvidence) { event.preventDefault(); const runId = insightEvidence.dataset.runId; if (runId) { state.runId = runId; localStorage.setItem(KEY.run, runId); go("teleagent-result"); } else toast(`依据来自对话轮次：${insightEvidence.dataset.turns || "已留存"}`); return; }
      const plan = event.target.closest(".js-generate-plan");
      if (plan) { event.preventDefault(); generatePlan(plan); return; }
      const complete = event.target.closest(".js-complete-plan");
      if (complete) { event.preventDefault(); completePlan(complete); return; }
      const confirmPlan = event.target.closest(".js-confirm-plan");
      if (confirmPlan) { event.preventDefault(); saveCompletedPlan(confirmPlan); return; }
      const cancelPlan = event.target.closest(".js-cancel-plan");
      if (cancelPlan) { event.preventDefault(); const card = cancelPlan.closest(".plan-card"); card.querySelector(".plan-reflection")?.remove(); const trigger = card.querySelector(".js-complete-plan"); if (trigger) trigger.hidden = false; return; }
      const timelineFilter = event.target.closest(".js-timeline-filter");
      if (timelineFilter) { event.preventDefault(); const filter = timelineFilter.dataset.filter; $$(".js-timeline-filter").forEach((item) => { item.classList.toggle("btn-secondary", item === timelineFilter); item.classList.toggle("btn-ghost", item !== timelineFilter); }); $$("[data-event-group]").forEach((item) => { item.hidden = filter !== "all" && item.dataset.eventGroup !== filter; }); return; }
      if (event.target.closest(".js-go-course")) { event.preventDefault(); go("course-detail"); }
    }, true);
  }

  function showBootError(error) {
    const main = $("#main");
    if (!main) return;
    main.insertAdjacentHTML("afterbegin", `<div class="connection-error"><strong>平台服务未连接</strong><span>${esc(error.message)}</span><small>请通过 start-platform.ps1 启动，不要直接双击 HTML 文件。</small></div>`);
  }

  async function init() {
    installEvents();
    try {
      const initial = state.learnerId ? withLearner("/api/bootstrap") : "/api/bootstrap";
      state.bootstrap = await api(initial);
      state.learnerId = String(state.bootstrap.learner.learner_id);
      localStorage.setItem(KEY.learner, state.learnerId);
      if (!state.bootstrap.courses.some((course) => String(course.course_id) === String(state.courseId))) setCourse(state.bootstrap.courses[0]?.course_id || "");
      hydrateCommon();
      const route = ROUTE();
      if (route === "home") hydrateHome();
      if (route === "courses") hydrateCourses();
      if (route === "add-course") setupAudioDropzone();
      if (["course-detail", "course-knowledge", "course-relations", "course-interactions"].includes(route)) await hydrateDetail();
      if (route === "course-transcript") await hydrateTranscript();
      if (route === "teleagent-delivery") await hydrateDelivery();
      if (route === "teleagent-result") await hydrateResult();
      if (["growth-overview", "growth-knowledge", "growth-timeline", "learning-plan", "growth-profile"].includes(route)) await hydrateGrowth(route);
    } catch (error) { showBootError(error); }
  }

  init();
})();
