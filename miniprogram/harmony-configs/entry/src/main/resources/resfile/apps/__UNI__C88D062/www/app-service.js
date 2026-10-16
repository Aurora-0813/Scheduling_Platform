if (typeof Promise !== "undefined" && !Promise.prototype.finally) {
  Promise.prototype.finally = function(callback) {
    const promise = this.constructor;
    return this.then(
      (value) => promise.resolve(callback()).then(() => value),
      (reason) => promise.resolve(callback()).then(() => {
        throw reason;
      })
    );
  };
}
;
if (typeof uni !== "undefined" && uni && uni.requireGlobal) {
  const global = uni.requireGlobal();
  ArrayBuffer = global.ArrayBuffer;
  Int8Array = global.Int8Array;
  Uint8Array = global.Uint8Array;
  Uint8ClampedArray = global.Uint8ClampedArray;
  Int16Array = global.Int16Array;
  Uint16Array = global.Uint16Array;
  Int32Array = global.Int32Array;
  Uint32Array = global.Uint32Array;
  Float32Array = global.Float32Array;
  Float64Array = global.Float64Array;
  BigInt64Array = global.BigInt64Array;
  BigUint64Array = global.BigUint64Array;
}
;
if (uni.restoreGlobal) {
  uni.restoreGlobal(Vue, weex, plus, setTimeout, clearTimeout, setInterval, clearInterval);
}
(function(vue) {
  "use strict";
  function currentPageCaptureScreenshot(fullPage, callback) {
    var _a;
    const pages = getCurrentPages();
    const currentPage = pages[pages.length - 1];
    (_a = currentPage.vm) === null || _a === void 0 ? void 0 : _a.$viewToTempFilePath({
      wholeContent: fullPage,
      overwrite: true,
      success: (res) => {
        const fileManager = uni.getFileSystemManager();
        fileManager.readFile({
          encoding: "base64",
          filePath: res.tempFilePath,
          success(readFileRes) {
            callback(readFileRes.data, "");
          },
          fail(err) {
            callback("", `captureScreenshot fail: ${JSON.stringify(err)}`);
          }
        });
      },
      fail: (err) => {
        callback("", `captureScreenshot fail: ${JSON.stringify(err)}`);
      }
    });
  }
  function initRuntimeSocket(hosts, port, id) {
    if (hosts == "" || port == "" || id == "")
      return Promise.resolve(null);
    return hosts.split(",").reduce((promise, host) => {
      return promise.then((socket) => {
        if (socket != null)
          return Promise.resolve(socket);
        return tryConnectSocket(host, port, id);
      });
    }, Promise.resolve(null));
  }
  const SOCKET_TIMEOUT = 500;
  function tryConnectSocket(host, port, id) {
    return new Promise((resolve, reject) => {
      const socket = uni.connectSocket({
        url: `ws://${host}:${port}/${id}`,
        multiple: true,
        // 支付宝小程序 是否开启多实例
        fail() {
          resolve(null);
        }
      });
      const timer = setTimeout(() => {
        socket.close({
          code: 1006,
          reason: "connect timeout"
        });
        resolve(null);
      }, SOCKET_TIMEOUT);
      socket.onOpen((e) => {
        clearTimeout(timer);
        resolve(socket);
      });
      socket.onClose((e) => {
        clearTimeout(timer);
        resolve(null);
      });
      socket.onError((e) => {
        clearTimeout(timer);
        resolve(null);
      });
      socket.onMessage((result) => {
        const message = JSON.parse(result.data);
        if (message["type"] == "screencap") {
          const id2 = message["id"];
          currentPageCaptureScreenshot(message.fullPage, (base64, error) => {
            socket.send({
              data: JSON.stringify({
                id: id2,
                base64,
                error
              })
            });
          });
        }
        resolve(null);
      });
    });
  }
  const CONSOLE_TYPES = ["log", "warn", "error", "info", "debug"];
  const originalConsole = /* @__PURE__ */ CONSOLE_TYPES.reduce((methods, type) => {
    methods[type] = console[type].bind(console);
    return methods;
  }, {});
  let sendError = null;
  const errorQueue = /* @__PURE__ */ new Set();
  const errorExtra = {};
  function sendErrorMessages(errors) {
    if (sendError == null) {
      errors.forEach((error) => {
        errorQueue.add(error);
      });
      return;
    }
    const data = errors.map((err) => {
      if (typeof err === "string") {
        return err;
      }
      const isPromiseRejection = err && "promise" in err && "reason" in err;
      const prefix = isPromiseRejection ? "UnhandledPromiseRejection: " : "";
      if (isPromiseRejection) {
        err = err.reason;
      }
      if (err instanceof Error && err.stack) {
        if (err.message && !err.stack.includes(err.message)) {
          return `${prefix}${err.message}
${err.stack}`;
        }
        return `${prefix}${err.stack}`;
      }
      if (typeof err === "object" && err !== null) {
        try {
          return prefix + JSON.stringify(err);
        } catch (err2) {
          return prefix + String(err2);
        }
      }
      return prefix + String(err);
    }).filter(Boolean);
    if (data.length > 0) {
      sendError(JSON.stringify(Object.assign({
        type: "error",
        data
      }, errorExtra)));
    }
  }
  function setSendError(value, extra = {}) {
    sendError = value;
    Object.assign(errorExtra, extra);
    if (value != null && errorQueue.size > 0) {
      const errors = Array.from(errorQueue);
      errorQueue.clear();
      sendErrorMessages(errors);
    }
  }
  function initOnError() {
    function onError(error) {
      try {
        if (typeof PromiseRejectionEvent !== "undefined" && error instanceof PromiseRejectionEvent && error.reason instanceof Error && error.reason.message && error.reason.message.includes(`Cannot create property 'errMsg' on string 'taskId`)) {
          return;
        }
        if (false)
          ;
        sendErrorMessages([error]);
      } catch (err) {
        originalConsole.error(err);
      }
    }
    if (typeof uni !== "undefined") {
      if (typeof uni.onError === "function") {
        uni.onError(onError);
      }
      if (typeof uni.onUnhandledRejection === "function") {
        uni.onUnhandledRejection(onError);
      }
    }
    return function offError() {
      if (typeof uni !== "undefined") {
        if (typeof uni.offError === "function") {
          uni.offError(onError);
        }
        if (typeof uni.offUnhandledRejection === "function") {
          uni.offUnhandledRejection(onError);
        }
      }
    };
  }
  function formatMessage(type, args) {
    const messageType = type === "warn" ? "warning" : type;
    try {
      return {
        type: messageType,
        args: formatArgs(args)
      };
    } catch (e) {
    }
    return {
      type: messageType,
      args: []
    };
  }
  function formatArgs(args) {
    return args.map((arg) => formatArg(arg));
  }
  function formatArg(arg, depth = 0) {
    if (depth >= 7) {
      return {
        type: "object",
        value: "[Maximum depth reached]"
      };
    }
    const type = typeof arg;
    switch (type) {
      case "string":
        return formatString(arg);
      case "number":
        return formatNumber(arg);
      case "boolean":
        return formatBoolean(arg);
      case "object":
        try {
          return formatObject(arg, depth);
        } catch (e) {
          return {
            type: "object",
            value: {
              properties: []
            }
          };
        }
      case "undefined":
        return formatUndefined();
      case "function":
        return formatFunction(arg);
      case "symbol": {
        return formatSymbol(arg);
      }
      case "bigint":
        return formatBigInt(arg);
    }
  }
  function formatFunction(value) {
    return {
      type: "function",
      value: `function ${value.name}() {}`
    };
  }
  function formatUndefined() {
    return {
      type: "undefined"
    };
  }
  function formatBoolean(value) {
    return {
      type: "boolean",
      value: String(value)
    };
  }
  function formatNumber(value) {
    return {
      type: "number",
      value: String(value)
    };
  }
  function formatBigInt(value) {
    return {
      type: "bigint",
      value: String(value)
    };
  }
  function formatString(value) {
    return {
      type: "string",
      value
    };
  }
  function formatSymbol(value) {
    return {
      type: "symbol",
      value: value.description
    };
  }
  function formatObject(value, depth) {
    if (value === null) {
      return {
        type: "null"
      };
    }
    {
      if (isComponentPublicInstance(value)) {
        return formatComponentPublicInstance(value, depth);
      }
      if (isComponentInternalInstance(value)) {
        return formatComponentInternalInstance(value, depth);
      }
      if (isUniElement(value)) {
        return formatUniElement(value, depth);
      }
      if (isCSSStyleDeclaration(value)) {
        return formatCSSStyleDeclaration(value, depth);
      }
    }
    if (Array.isArray(value)) {
      return {
        type: "object",
        subType: "array",
        value: {
          properties: value.map((v, i) => formatArrayElement(v, i, depth + 1))
        }
      };
    }
    if (value instanceof Set) {
      return {
        type: "object",
        subType: "set",
        className: "Set",
        description: `Set(${value.size})`,
        value: {
          entries: Array.from(value).map((v) => formatSetEntry(v, depth + 1))
        }
      };
    }
    if (value instanceof Map) {
      return {
        type: "object",
        subType: "map",
        className: "Map",
        description: `Map(${value.size})`,
        value: {
          entries: Array.from(value.entries()).map((v) => formatMapEntry(v, depth + 1))
        }
      };
    }
    if (value instanceof Promise) {
      return {
        type: "object",
        subType: "promise",
        value: {
          properties: []
        }
      };
    }
    if (value instanceof RegExp) {
      return {
        type: "object",
        subType: "regexp",
        value: String(value),
        className: "Regexp"
      };
    }
    if (value instanceof Date) {
      return {
        type: "object",
        subType: "date",
        value: String(value),
        className: "Date"
      };
    }
    if (value instanceof Error) {
      return {
        type: "object",
        subType: "error",
        value: value.message || String(value),
        className: value.name || "Error"
      };
    }
    let className = void 0;
    {
      const constructor = value.constructor;
      if (constructor) {
        if (constructor.get$UTSMetadata$) {
          className = constructor.get$UTSMetadata$().name;
        }
      }
    }
    let entries = Object.entries(value);
    if (isHarmonyBuilderParams(value)) {
      entries = entries.filter(([key]) => key !== "modifier" && key !== "nodeContent");
    }
    return {
      type: "object",
      className,
      value: {
        properties: entries.map((entry) => formatObjectProperty(entry[0], entry[1], depth + 1))
      }
    };
  }
  function isHarmonyBuilderParams(value) {
    return value.modifier && value.modifier._attribute && value.nodeContent;
  }
  function isComponentPublicInstance(value) {
    return value.$ && isComponentInternalInstance(value.$);
  }
  function isComponentInternalInstance(value) {
    return value.type && value.uid != null && value.appContext;
  }
  function formatComponentPublicInstance(value, depth) {
    return {
      type: "object",
      className: "ComponentPublicInstance",
      value: {
        properties: Object.entries(value.$.type).map(([name, value2]) => formatObjectProperty(name, value2, depth + 1))
      }
    };
  }
  function formatComponentInternalInstance(value, depth) {
    return {
      type: "object",
      className: "ComponentInternalInstance",
      value: {
        properties: Object.entries(value.type).map(([name, value2]) => formatObjectProperty(name, value2, depth + 1))
      }
    };
  }
  function isUniElement(value) {
    return value.style && value.tagName != null && value.nodeName != null;
  }
  function formatUniElement(value, depth) {
    return {
      type: "object",
      // 非 x 没有 UniElement 的概念
      // className: 'UniElement',
      value: {
        properties: Object.entries(value).filter(([name]) => [
          "id",
          "tagName",
          "nodeName",
          "dataset",
          "offsetTop",
          "offsetLeft",
          "style"
        ].includes(name)).map(([name, value2]) => formatObjectProperty(name, value2, depth + 1))
      }
    };
  }
  function isCSSStyleDeclaration(value) {
    return typeof value.getPropertyValue === "function" && typeof value.setProperty === "function" && value.$styles;
  }
  function formatCSSStyleDeclaration(style, depth) {
    return {
      type: "object",
      value: {
        properties: Object.entries(style.$styles).map(([name, value]) => formatObjectProperty(name, value, depth + 1))
      }
    };
  }
  function formatObjectProperty(name, value, depth) {
    const result = formatArg(value, depth);
    result.name = name;
    return result;
  }
  function formatArrayElement(value, index, depth) {
    const result = formatArg(value, depth);
    result.name = `${index}`;
    return result;
  }
  function formatSetEntry(value, depth) {
    return {
      value: formatArg(value, depth)
    };
  }
  function formatMapEntry(value, depth) {
    return {
      key: formatArg(value[0], depth),
      value: formatArg(value[1], depth)
    };
  }
  let sendConsole = null;
  const messageQueue = [];
  const messageExtra = {};
  const EXCEPTION_BEGIN_MARK = "---BEGIN:EXCEPTION---";
  const EXCEPTION_END_MARK = "---END:EXCEPTION---";
  function sendConsoleMessages(messages) {
    if (sendConsole == null) {
      messageQueue.push(...messages);
      return;
    }
    sendConsole(JSON.stringify(Object.assign({
      type: "console",
      data: messages
    }, messageExtra)));
  }
  function setSendConsole(value, extra = {}) {
    sendConsole = value;
    Object.assign(messageExtra, extra);
    if (value != null && messageQueue.length > 0) {
      const messages = messageQueue.slice();
      messageQueue.length = 0;
      sendConsoleMessages(messages);
    }
  }
  function rewriteConsole() {
    {
      if (typeof UTSProxyObject === "object" && UTSProxyObject !== null && typeof UTSProxyObject.invokeSync === "function") {
        UTSProxyObject.invokeSync("__UniConsole", "setSendConsoleMessages", [
          sendConsoleMessages
        ]);
      }
    }
    function wrapConsole(type) {
      return function(...args) {
        if (type === "error" && args.length === 1) {
          const arg = args[0];
          if (typeof arg === "string" && arg.startsWith(EXCEPTION_BEGIN_MARK)) {
            const startIndex = EXCEPTION_BEGIN_MARK.length;
            const endIndex = arg.length - EXCEPTION_END_MARK.length;
            sendErrorMessages([arg.slice(startIndex, endIndex)]);
            return;
          } else if (arg instanceof Error) {
            sendErrorMessages([arg]);
            return;
          }
        }
        sendConsoleMessages([formatMessage(type, args)]);
      };
    }
    if (isConsoleWritable()) {
      CONSOLE_TYPES.forEach((type) => {
        console[type] = wrapConsole(type);
      });
      return function restoreConsole() {
        CONSOLE_TYPES.forEach((type) => {
          console[type] = originalConsole[type];
        });
      };
    } else {
      {
        if (typeof uni !== "undefined" && uni.__f__) {
          const oldLog = uni.__f__;
          if (oldLog) {
            uni.__f__ = function(...args) {
              const [type, filename, ...rest] = args;
              oldLog(type, "", ...rest);
              sendConsoleMessages([formatMessage(type, [...rest, filename])]);
            };
            return function restoreConsole() {
              uni.__f__ = oldLog;
            };
          }
        }
      }
    }
    return function restoreConsole() {
      {
        if (typeof UTSProxyObject === "object" && UTSProxyObject !== null && typeof UTSProxyObject.invokeSync === "function") {
          UTSProxyObject.invokeSync("__UniConsole", "restoreConsole", []);
        }
      }
    };
  }
  function isConsoleWritable() {
    const value = console.log;
    const sym = Symbol();
    try {
      console.log = sym;
    } catch (ex) {
      return false;
    }
    const isWritable = console.log === sym;
    console.log = value;
    return isWritable;
  }
  const UNI_CONSOLE_RUNTIME_PROMISE = "__uni_console_runtime_promise__";
  function initRuntimeSocketService() {
    const hosts = "127.0.0.1,192.168.23.1,192.168.88.1,192.168.8.62";
    const port = "8090";
    const id = "app-harmony_rZ81Nf";
    const runtimeGlobal = getRuntimeGlobal();
    const existingPromise = runtimeGlobal === null || runtimeGlobal === void 0 ? void 0 : runtimeGlobal[UNI_CONSOLE_RUNTIME_PROMISE];
    if (existingPromise) {
      return existingPromise;
    }
    let runtimePromise = initRuntimeSocketServiceOnce(hosts, port, id);
    if (runtimeGlobal) {
      runtimePromise = runtimePromise.then((success) => {
        if (!success && runtimeGlobal[UNI_CONSOLE_RUNTIME_PROMISE] === runtimePromise) {
          delete runtimeGlobal[UNI_CONSOLE_RUNTIME_PROMISE];
        }
        return success;
      }, (error) => {
        if (runtimeGlobal[UNI_CONSOLE_RUNTIME_PROMISE] === runtimePromise) {
          delete runtimeGlobal[UNI_CONSOLE_RUNTIME_PROMISE];
        }
        throw error;
      });
      runtimeGlobal[UNI_CONSOLE_RUNTIME_PROMISE] = runtimePromise;
    }
    return runtimePromise;
  }
  function initRuntimeSocketServiceOnce(hosts, port, id) {
    const lazy = typeof swan !== "undefined";
    let restoreError = lazy ? () => {
    } : initOnError();
    let restoreConsole = lazy ? () => {
    } : rewriteConsole();
    return Promise.resolve().then(() => {
      if (lazy) {
        restoreError = initOnError();
        restoreConsole = rewriteConsole();
      }
      return initRuntimeSocket(hosts, port, id).then((socket) => {
        if (!socket) {
          restoreError();
          restoreConsole();
          originalConsole.error(wrapError("开发模式下日志通道建立 socket 连接失败。"));
          originalConsole.error(wrapError("如果是运行到真机，请确认手机与电脑处于同一网络。"));
          return false;
        }
        socket.onClose(() => {
          {
            originalConsole.error(wrapError("手机端日志通道 socket 连接已断开，请重启基座应用或重新运行。"));
          }
          restoreError();
          restoreConsole();
        });
        setSendConsole((data) => {
          socket.send({
            data
          });
        });
        setSendError((data) => {
          socket.send({
            data
          });
        });
        return true;
      });
    });
  }
  const ERROR_CHAR = "‌";
  function wrapError(error) {
    return `${ERROR_CHAR}${error}${ERROR_CHAR}`;
  }
  function getRuntimeGlobal() {
    const miniProgramGlobal = getMiniProgramGlobal();
    if (miniProgramGlobal) {
      return miniProgramGlobal;
    }
    if (typeof globalThis !== "undefined") {
      return globalThis;
    }
  }
  function getMiniProgramGlobal() {
    if (typeof wx !== "undefined") {
      return wx;
    } else if (typeof my !== "undefined") {
      return my;
    } else if (typeof tt !== "undefined") {
      return tt;
    } else if (typeof swan !== "undefined") {
      return swan;
    } else if (typeof qq !== "undefined") {
      return qq;
    } else if (typeof ks !== "undefined") {
      return ks;
    } else if (typeof jd !== "undefined") {
      return jd;
    } else if (typeof xhs !== "undefined") {
      return xhs;
    } else if (typeof has !== "undefined") {
      return has;
    } else if (typeof qa !== "undefined") {
      return qa;
    }
  }
  initRuntimeSocketService();
  const _export_sfc = (sfc, props) => {
    const target = sfc.__vccOpts || sfc;
    for (const [key, val] of props) {
      target[key] = val;
    }
    return target;
  };
  const _sfc_main$g = {
    __name: "mp-nav-bar",
    props: {
      title: { type: String, default: "" },
      /** 右侧文字，如「普通用户」。不能放图标按钮——会被胶囊遮住 */
      right: { type: String, default: "" },
      /** 是否显示返回箭头，二级页传 true */
      back: { type: Boolean, default: false },
      /** M1 首页样式：大号左对齐标题，无返回 */
      big: { type: Boolean, default: false },
      bg: { type: String, default: "#ffffff" },
      border: { type: Boolean, default: true }
    },
    emits: ["right"],
    setup(__props, { expose: __expose, emit: __emit }) {
      __expose();
      const props = __props;
      const emit = __emit;
      const statusBarHeight = vue.ref(20);
      const navBarHeight = vue.ref(44);
      const rightGap = vue.ref(12);
      function measure() {
        let statusBar = 20;
        let windowWidth = 375;
        try {
          const win = (typeof uni.getWindowInfo === "function" ? uni.getWindowInfo() : null) || uni.getSystemInfoSync();
          if (win) {
            if (win.statusBarHeight)
              statusBar = win.statusBarHeight;
            if (win.windowWidth)
              windowWidth = win.windowWidth;
          }
        } catch (e) {
        }
        let navBar = 44;
        let gap = 12;
        if (typeof uni.getMenuButtonBoundingClientRect === "function") {
          try {
            const rect = uni.getMenuButtonBoundingClientRect();
            if (rect && rect.height && rect.top >= statusBar) {
              navBar = (rect.top - statusBar) * 2 + rect.height;
            }
            if (rect && rect.left) {
              gap = windowWidth - rect.left;
            }
          } catch (e) {
          }
        }
        statusBarHeight.value = statusBar;
        navBarHeight.value = navBar;
        rightGap.value = gap;
      }
      measure();
      const totalHeight = vue.computed(() => statusBarHeight.value + navBarHeight.value);
      const fixedStyle = vue.computed(() => ({
        paddingTop: statusBarHeight.value + "px",
        background: props.bg
      }));
      const innerStyle = vue.computed(() => ({
        height: navBarHeight.value + "px",
        paddingRight: rightGap.value + "px",
        borderBottomWidth: props.border ? "1px" : "0px"
      }));
      const holderStyle = vue.computed(() => ({
        height: totalHeight.value + "px"
      }));
      function goBack() {
        const pages = getCurrentPages();
        if (pages && pages.length > 1) {
          uni.navigateBack();
        } else {
          uni.reLaunch({ url: "/pages/index/index" });
        }
      }
      function onRight() {
        emit("right");
      }
      const __returned__ = { props, emit, statusBarHeight, navBarHeight, rightGap, measure, totalHeight, fixedStyle, innerStyle, holderStyle, goBack, onRight, ref: vue.ref, computed: vue.computed };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$f(_ctx, _cache, $props, $setup, $data, $options) {
    return vue.openBlock(), vue.createElementBlock("view", { class: "nb" }, [
      vue.createElementVNode(
        "view",
        {
          class: "nb-fixed",
          style: vue.normalizeStyle($setup.fixedStyle)
        },
        [
          vue.createElementVNode(
            "view",
            {
              class: "nb-inner",
              style: vue.normalizeStyle($setup.innerStyle)
            },
            [
              $props.back ? (vue.openBlock(), vue.createElementBlock("text", {
                key: 0,
                class: "nb-back",
                onClick: $setup.goBack
              }, "‹")) : vue.createCommentVNode("v-if", true),
              $props.big ? (vue.openBlock(), vue.createElementBlock(
                "text",
                {
                  key: 1,
                  class: "nb-big"
                },
                vue.toDisplayString($props.title),
                1
                /* TEXT */
              )) : (vue.openBlock(), vue.createElementBlock(
                "text",
                {
                  key: 2,
                  class: "nb-title"
                },
                vue.toDisplayString($props.title),
                1
                /* TEXT */
              )),
              $props.right ? (vue.openBlock(), vue.createElementBlock(
                "text",
                {
                  key: 3,
                  class: "nb-right",
                  onClick: $setup.onRight
                },
                vue.toDisplayString($props.right),
                1
                /* TEXT */
              )) : vue.createCommentVNode("v-if", true)
            ],
            4
            /* STYLE */
          )
        ],
        4
        /* STYLE */
      ),
      vue.createElementVNode(
        "view",
        {
          class: "nb-holder",
          style: vue.normalizeStyle($setup.holderStyle)
        },
        null,
        4
        /* STYLE */
      )
    ]);
  }
  const __easycom_0 = /* @__PURE__ */ _export_sfc(_sfc_main$g, [["render", _sfc_render$f], ["__scopeId", "data-v-1de34ced"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/components/mp-nav-bar/mp-nav-bar.vue"]]);
  const ON_SHOW = "onShow";
  const ON_LAUNCH = "onLaunch";
  const ON_LOAD = "onLoad";
  const ON_UNLOAD = "onUnload";
  function resolveEasycom(component, easycom) {
    return typeof component === "string" ? easycom : component;
  }
  const createLifeCycleHook = (lifecycle, flag = 0) => (hook, target = vue.getCurrentInstance()) => {
    if (vue.isInSSRComponentSetup)
      return;
    vue.injectHook(lifecycle, hook, target);
  };
  const onShow = /* @__PURE__ */ createLifeCycleHook(
    ON_SHOW,
    2
    /* HookFlags.PAGE */
  );
  const onLaunch = /* @__PURE__ */ createLifeCycleHook(
    ON_LAUNCH,
    1
    /* HookFlags.APP */
  );
  const onLoad = /* @__PURE__ */ createLifeCycleHook(
    ON_LOAD,
    2
    /* HookFlags.PAGE */
  );
  const onUnload = /* @__PURE__ */ createLifeCycleHook(
    ON_UNLOAD,
    2
    /* HookFlags.PAGE */
  );
  const TABS = [
    { index: 0, icon: "🏠", label: "首页", path: "/pages/index/index" },
    { index: 1, icon: "🗓", label: "预约", path: "/pages/order/list" },
    { index: 2, icon: "📷", label: "巡检", path: "/pages/inspect/index" },
    { index: 3, icon: "🔔", label: "消息", path: "/pages/message/list" },
    { index: 4, icon: "👤", label: "我的", path: "/pages/mine/index" }
  ];
  const BASE_URL = "http://192.168.43.10:8000";
  const API_PREFIX = "/api/v1";
  const MOCK_PREFIX = "/api/v1/mock";
  const API_MODE = "real";
  const REQUEST_TIMEOUT = 24e4;
  const STORAGE_KEYS = {
    ACCESS: "sp_access_token",
    REFRESH: "sp_refresh_token"
  };
  const IMAGE_LIMIT = {
    MAX_MB: 5,
    EXT: ["jpg", "jpeg", "png", "webp"]
  };
  const RECORD_OPTIONS = {
    duration: 6e4,
    sampleRate: 16e3,
    numberOfChannels: 1,
    encodeBitRate: 48e3,
    format: "wav"
  };
  function getAccessToken() {
    return uni.getStorageSync(STORAGE_KEYS.ACCESS) || "";
  }
  function getRefreshToken() {
    return uni.getStorageSync(STORAGE_KEYS.REFRESH) || "";
  }
  function setTokens({ accessToken, refreshToken } = {}) {
    if (accessToken)
      uni.setStorageSync(STORAGE_KEYS.ACCESS, accessToken);
    if (refreshToken)
      uni.setStorageSync(STORAGE_KEYS.REFRESH, refreshToken);
  }
  function clearTokens() {
    uni.removeStorageSync(STORAGE_KEYS.ACCESS);
    uni.removeStorageSync(STORAGE_KEYS.REFRESH);
  }
  function hasToken() {
    return !!getAccessToken();
  }
  let loadingDepth = 0;
  let loadingVisible = false;
  function toast(title, duration = 2e3) {
    dropLoading();
    uni.showToast({ title: String(title || "操作失败"), icon: "none", duration });
  }
  function toastOk(title = "操作成功") {
    dropLoading();
    uni.showToast({ title, icon: "success", duration: 1500 });
  }
  function showLoading(title = "加载中…") {
    loadingDepth += 1;
    if (loadingVisible)
      return;
    loadingVisible = true;
    uni.showLoading({ title, mask: true });
  }
  function hideLoading() {
    if (loadingDepth === 0)
      return;
    loadingDepth -= 1;
    if (loadingDepth > 0)
      return;
    dropLoading();
  }
  function resetLoading() {
    loadingDepth = 0;
    dropLoading();
  }
  function dropLoading() {
    if (!loadingVisible)
      return;
    loadingVisible = false;
    uni.hideLoading();
  }
  function confirm(content, title = "提示", confirmText = "确定") {
    const opts = content !== null && typeof content === "object" ? content : { content, title, confirmText };
    return new Promise((resolve) => {
      uni.showModal({
        title: opts.title || "提示",
        content: opts.content || "",
        confirmText: opts.confirmText || "确定",
        cancelText: opts.cancelText || "取消",
        confirmColor: opts.confirmColor || "#409EFF",
        success: (res) => resolve(!!res.confirm),
        fail: () => resolve(false)
      });
    });
  }
  const CODE = {
    OK: 200,
    /** accessToken 过期，应触发续期 */
    ACCESS_EXPIRED: 40103,
    /** 用 refreshToken 调业务接口 */
    REFRESH_AS_ACCESS: 40104,
    /** Redis 不可用 —— 服务问题，不是登录问题 */
    REDIS_DOWN: 50301
  };
  const AUTH_FAIL_CODES = [
    40100,
    // 用户已删除
    40101,
    // 未携带 token
    40102,
    // 签名/结构错误
    40104,
    // 拿 refreshToken 调业务接口
    40108,
    // 账号被禁用
    40302
    // 未分配角色
  ];
  function buildUrl(path, useMock) {
    return BASE_URL + (useMock ? MOCK_PREFIX : API_PREFIX) + path;
  }
  function buildHeader(extra, auth) {
    const header = { "Content-Type": "application/json", ...extra };
    if (auth) {
      const token = getAccessToken();
      if (token)
        header.Authorization = `Bearer ${token}`;
    }
    return header;
  }
  function isServerDown(statusCode, code) {
    if (statusCode >= 500)
      return true;
    return typeof code === "number" && code >= 5e4 && code !== CODE.REDIS_DOWN;
  }
  function makeError(message, kind, extra = {}) {
    const err = new Error(message);
    err.kind = kind;
    Object.assign(err, extra);
    return err;
  }
  let refreshPromise = null;
  function doRefresh() {
    const refreshToken = getRefreshToken();
    if (!refreshToken)
      return Promise.reject(makeError("无 refreshToken", "AUTH"));
    return new Promise((resolve, reject) => {
      uni.request({
        // refresh 不需要 Authorization 头
        url: BASE_URL + API_PREFIX + "/auth/refresh",
        method: "POST",
        header: { "Content-Type": "application/json" },
        data: { refreshToken },
        // 续期是「快进快出」的一次调用，不该跟着主请求的 240 秒一起等 ——
        // 后端不可达时要尽快失败，否则用户会在一个已经失效的页面上干等 4 分钟。
        timeout: 15e3,
        success: (res) => {
          const body = res.data;
          if (body && body.code === CODE.OK) {
            setTokens(body.data);
            resolve(body.data);
          } else {
            reject(makeError(body && body.message || "登录已过期", "AUTH", { code: body && body.code }));
          }
        },
        fail: () => reject(makeError("网络请求失败", "NETWORK"))
      });
    });
  }
  function refreshAccessToken() {
    if (!refreshPromise) {
      refreshPromise = doRefresh();
      refreshPromise.then(
        () => {
          refreshPromise = null;
        },
        () => {
          refreshPromise = null;
        }
      );
    }
    return refreshPromise;
  }
  let lastRedirectAt = 0;
  function redirectToLogin() {
    const now = Date.now();
    if (now - lastRedirectAt < 3e3)
      return;
    lastRedirectAt = now;
    uni.navigateTo({ url: "/pages/login/index" });
  }
  function tryFallback(method, path, data) {
    return void 0;
  }
  function rawRequest(options) {
    return new Promise((resolve, reject) => {
      uni.request({
        // ⚠️ **默认超时必须放在展开之前（2026-09-30 修）。**
        // 原先写的是 `...options` 然后 `timeout: REQUEST_TIMEOUT`，
        // 后者**覆盖**了前者 —— 于是调用方传任何 timeout 都不生效，
        // 全站被钉死在 REQUEST_TIMEOUT 上。现在顺序反过来：默认值先给，
        // 调用方传了就覆盖它（`request()` 的 options.timeout）。
        timeout: REQUEST_TIMEOUT,
        ...options,
        success: resolve,
        fail: reject
      });
    });
  }
  async function request(options) {
    const {
      path,
      method = "GET",
      data,
      header,
      auth = true,
      mock,
      silent = false,
      // 逐请求超时。不传则用 config 的 REQUEST_TIMEOUT（已放宽到 240s）。
      timeout,
      _retried = false
    } = options;
    const useMock = mock === void 0 ? API_MODE === "mock" : !!mock;
    if (auth && !getAccessToken()) {
      throw makeError("未登录", "NO_TOKEN");
    }
    let res;
    try {
      res = await rawRequest({
        url: buildUrl(path, useMock),
        method,
        data,
        header: buildHeader(header, auth),
        // 仅在调用方显式传入时才覆盖默认超时，避免把 undefined 塞进去
        ...timeout ? { timeout } : {}
      });
    } catch (e) {
      const fallback = tryFallback();
      if (fallback !== void 0)
        return fallback;
      throw makeError("网络连接失败，请确认后端服务已启动", "NETWORK");
    }
    const body = res.data;
    const code = body && typeof body === "object" ? body.code : void 0;
    if (code === CODE.OK)
      return body.data;
    if (code === CODE.ACCESS_EXPIRED && !_retried && auth) {
      try {
        await refreshAccessToken();
      } catch (e) {
        clearTokens();
        redirectToLogin();
        throw makeError("登录已过期，请重新登录", "AUTH");
      }
      return request({ ...options, _retried: true });
    }
    if (code === CODE.REDIS_DOWN) {
      throw makeError(body && body.message || "服务暂时不可用，请稍后重试", "SERVICE", { code });
    }
    if (AUTH_FAIL_CODES.indexOf(code) !== -1) {
      clearTokens();
      redirectToLogin();
      throw makeError(body && body.message || "登录状态无效，请重新登录", "AUTH", { code });
    }
    if (isServerDown(res.statusCode, code)) {
      const fallback = tryFallback();
      if (fallback !== void 0)
        return fallback;
    }
    const message = body && body.message || `请求失败（HTTP ${res.statusCode}）`;
    const err = makeError(message, "BIZ", { code, data: body && body.data });
    if (!silent)
      toast(message);
    throw err;
  }
  function upload(options) {
    const {
      path,
      filePath,
      name = "file",
      formData = {},
      auth = true,
      mock,
      silent = false
    } = options;
    const useMock = mock === void 0 ? API_MODE === "mock" : !!mock;
    return new Promise((resolve, reject) => {
      const header = {};
      if (auth) {
        const token = getAccessToken();
        if (token)
          header.Authorization = `Bearer ${token}`;
      }
      uni.uploadFile({
        url: buildUrl(path, useMock),
        filePath,
        name,
        formData,
        header,
        // 上传确实比普通请求慢，但**不能**跟着 REQUEST_TIMEOUT 一起放大：
        // 后者现在是 240000（为 /agent/schedule 那 39~105 秒留的余量），
        // 乘 2 会变成 480 秒 —— 用户要干等 8 分钟才看到失败。
        // 上传是「传字节 + 一次识别」，120 秒足够（60 秒录音的 base64 约 2.6MB）。
        timeout: options.timeout || 12e4,
        success: (res) => {
          let body;
          try {
            body = JSON.parse(res.data);
          } catch (e) {
            const fallback = tryFallback();
            if (fallback !== void 0)
              return resolve(fallback);
            return reject(makeError("返回数据解析失败", "PARSE"));
          }
          if (body && body.code === CODE.OK)
            return resolve(body.data);
          const message = body && body.message || "上传失败";
          if (!silent)
            toast(message);
          return reject(makeError(message, "BIZ", { code: body && body.code }));
        },
        fail: () => {
          const fallback = tryFallback();
          if (fallback !== void 0)
            return resolve(fallback);
          reject(makeError("网络连接失败，请确认后端服务已启动", "NETWORK"));
        }
      });
    });
  }
  function absoluteUrl(path) {
    if (!path)
      return "";
    if (/^https?:\/\//.test(path))
      return path;
    return BASE_URL + path;
  }
  const ROLE_TEXT = {
    // 代码写法（兼容旧数据 / 前端其它地方传值）
    admin: "系统管理员",
    resource_admin: "资源管理员",
    user: "普通用户",
    // 后端真实返回值：中文角色名，原样透传
    系统管理员: "系统管理员",
    管理员: "管理员",
    资源管理员: "资源管理员",
    普通用户: "普通用户"
  };
  function roleText$1(role) {
    const key = String(role == null ? "" : role).trim();
    if (!key)
      return "普通用户";
    return ROLE_TEXT[key] || key;
  }
  async function login({ username, password }) {
    const data = await request({
      path: "/auth/login",
      method: "POST",
      data: { username, password },
      auth: false,
      // 登录接口不需要 Authorization
      mock: false
      // 认证没有 mock 路由
    });
    setTokens(data);
    return data;
  }
  async function getInfo() {
    return request({ path: "/auth/info", method: "GET", mock: false });
  }
  async function logout() {
    try {
      await request({ path: "/auth/logout", method: "POST", data: {}, mock: false, silent: true });
    } catch (e) {
    }
    clearTokens();
  }
  const userStore = vue.reactive({
    /** @type {null|{id:number, username:string, role:string, avatar:string, permissions:string[]}} */
    info: null,
    role: "user",
    loggedIn: false,
    loading: false
  });
  function roleText() {
    return roleText$1(userStore.role);
  }
  function isAdmin() {
    return userStore.role === "系统管理员";
  }
  function displayName() {
    if (!userStore.info)
      return "访客";
    return userStore.info.username || "用户";
  }
  function restoreSession() {
    userStore.loggedIn = hasToken();
    if (userStore.loggedIn) {
      fetchInfo();
    }
  }
  async function fetchInfo() {
    userStore.loading = true;
    try {
      const info = await getInfo();
      userStore.info = info;
      userStore.role = info.role || "user";
      userStore.loggedIn = true;
    } catch (e) {
      if (e.kind === "AUTH") {
        userStore.loggedIn = false;
        userStore.info = null;
      }
    } finally {
      userStore.loading = false;
    }
  }
  async function doLogin({ username, password }) {
    const data = await login({ username, password });
    userStore.role = data.role || "user";
    userStore.loggedIn = true;
    await fetchInfo();
    return data;
  }
  async function doLogout() {
    await logout();
    clearTokens();
    userStore.loggedIn = false;
    userStore.info = null;
    userStore.role = "user";
  }
  const _sfc_main$f = {
    __name: "mp-tab-bar",
    props: {
      /** 当前选中的 tab 下标，页面里传常量即可 */
      current: { type: Number, default: 0 }
    },
    setup(__props, { expose: __expose }) {
      __expose();
      const props = __props;
      const tabs = vue.computed(() => TABS.filter((t) => t.label !== "巡检" || isAdmin()));
      function go(index) {
        if (index === props.current)
          return;
        const tab = TABS[index];
        if (!tab)
          return;
        uni.reLaunch({ url: tab.path });
      }
      const __returned__ = { props, tabs, go, computed: vue.computed, get TABS() {
        return TABS;
      }, get isAdmin() {
        return isAdmin;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$e(_ctx, _cache, $props, $setup, $data, $options) {
    return vue.openBlock(), vue.createElementBlock("view", { class: "tb" }, [
      vue.createElementVNode("view", { class: "tb-fixed" }, [
        vue.createElementVNode("view", { class: "tb-inner" }, [
          (vue.openBlock(true), vue.createElementBlock(
            vue.Fragment,
            null,
            vue.renderList($setup.tabs, (tab) => {
              return vue.openBlock(), vue.createElementBlock("view", {
                key: tab.path,
                class: vue.normalizeClass(["tb-item", { on: tab.index === $props.current }]),
                "hover-class": "tb-on",
                "hover-stay-time": 60,
                onClick: ($event) => $setup.go(tab.index)
              }, [
                vue.createElementVNode(
                  "text",
                  { class: "tb-ic" },
                  vue.toDisplayString(tab.icon),
                  1
                  /* TEXT */
                ),
                vue.createElementVNode(
                  "text",
                  { class: "tb-lb" },
                  vue.toDisplayString(tab.label),
                  1
                  /* TEXT */
                )
              ], 10, ["onClick"]);
            }),
            128
            /* KEYED_FRAGMENT */
          ))
        ])
      ]),
      vue.createElementVNode("view", { class: "tb-holder" })
    ]);
  }
  const __easycom_1$1 = /* @__PURE__ */ _export_sfc(_sfc_main$f, [["render", _sfc_render$e], ["__scopeId", "data-v-a2e9bfbb"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/components/mp-tab-bar/mp-tab-bar.vue"]]);
  const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }
  function parseDateTime(value) {
    if (!value)
      return null;
    if (value instanceof Date)
      return value;
    if (typeof value === "number")
      return new Date(value);
    const d = new Date(String(value).replace(/-/g, "/"));
    return isNaN(d.getTime()) ? null : d;
  }
  function formatDateTime(value = /* @__PURE__ */ new Date()) {
    const d = value instanceof Date ? value : parseDateTime(value);
    if (!d)
      return "";
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
  function formatTime(value) {
    const d = value instanceof Date ? value : parseDateTime(value);
    if (!d)
      return "";
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function formatMonthDay(value) {
    const d = value instanceof Date ? value : parseDateTime(value);
    if (!d)
      return "";
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }
  function formatWeekday(value) {
    const d = value instanceof Date ? value : parseDateTime(value);
    if (!d)
      return "";
    return WEEKDAYS[d.getDay()];
  }
  function startOfDay(d) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  }
  function relativeTime(value) {
    const d = value instanceof Date ? value : parseDateTime(value);
    if (!d)
      return "";
    const diff = Date.now() - d.getTime();
    if (diff < 60 * 1e3)
      return "刚刚";
    if (diff < 60 * 60 * 1e3)
      return `${Math.floor(diff / 6e4)} 分钟前`;
    const dayGap = Math.round((startOfDay(/* @__PURE__ */ new Date()) - startOfDay(d)) / 864e5);
    if (dayGap === 0)
      return formatTime(d);
    if (dayGap === 1)
      return `昨天 ${formatTime(d)}`;
    if (dayGap < 7)
      return `${dayGap} 天前`;
    return formatMonthDay(d);
  }
  function formatTimeRange(startTime, endTime) {
    const s = parseDateTime(startTime);
    const e = parseDateTime(endTime);
    if (!s)
      return "";
    if (!e)
      return formatDateTime(s);
    const sameDay = startOfDay(s) === startOfDay(e);
    const head = `${formatWeekday(s)} ${formatTime(s)} - ${formatTime(e)}`;
    return sameDay ? head : `${formatMonthDay(s)} ${formatTime(s)} - ${formatMonthDay(e)} ${formatTime(e)}`;
  }
  function formatMoney(value) {
    if (value === null || value === void 0 || value === "")
      return "";
    const s = String(value);
    return `¥ ${s}`;
  }
  function formatDuration(startTime, endTime) {
    const s = parseDateTime(startTime);
    const e = parseDateTime(endTime);
    if (!s || !e)
      return "";
    const minutes = Math.round((e.getTime() - s.getTime()) / 6e4);
    if (minutes < 60)
      return `${minutes} 分钟`;
    const hours = minutes / 60;
    return `${Number.isInteger(hours) ? hours : hours.toFixed(1)} 小时`;
  }
  function first(...values) {
    for (let i = 0; i < values.length; i += 1) {
      const v = values[i];
      if (v !== void 0 && v !== null && v !== "")
        return v;
    }
    return void 0;
  }
  function orderId(order) {
    if (!order)
      return void 0;
    return first(order.orderId, order.id);
  }
  function orderStatus(order) {
    if (!order)
      return void 0;
    return first(order.orderStatus, order.status);
  }
  function orderStatusText(order) {
    if (!order)
      return "";
    return first(order.statusText, order.statusLabel, "");
  }
  function spaceName(space) {
    if (!space)
      return "";
    return first(space.spaceName, space.name, "");
  }
  function listOf(data) {
    if (!data)
      return [];
    if (Array.isArray(data))
      return data;
    if (Array.isArray(data.list))
      return data.list;
    if (Array.isArray(data.items))
      return data.items;
    if (Array.isArray(data.records))
      return data.records;
    return [];
  }
  function totalOf(data) {
    if (!data)
      return 0;
    if (Array.isArray(data))
      return data.length;
    const total = first(data.total, data.totalCount, data.count);
    return typeof total === "number" ? total : listOf(data).length;
  }
  async function myOrders(params) {
    const data = await request({ path: "/orders/my", method: "GET", data: params });
    return { list: listOf(data), total: totalOf(data) };
  }
  function getOrder(orderId2) {
    return request({ path: "/orders/" + orderId2, method: "GET" });
  }
  function createOrder(payload) {
    return request({
      path: "/orders/create",
      method: "POST",
      data: {
        spaceId: payload.spaceId,
        deviceIds: payload.deviceIds || [],
        startTime: payload.startTime,
        endTime: payload.endTime,
        agentRequest: payload.agentRequest || "",
        agentTrace: payload.agentTrace || null
      }
    });
  }
  function confirmOrder(orderId2) {
    return request({ path: `/orders/${orderId2}/confirm`, method: "PUT" });
  }
  function completeOrder(orderId2) {
    return request({ path: `/orders/${orderId2}/complete`, method: "PUT" });
  }
  function cancelOrder(orderId2) {
    return request({ path: `/orders/${orderId2}/cancel`, method: "PUT" });
  }
  async function list(params) {
    const data = await request({ path: "/messages", method: "GET", data: params });
    return { list: listOf(data), total: totalOf(data) };
  }
  async function unread() {
    const data = await request({ path: "/messages/unread", method: "GET" });
    return { list: listOf(data), total: totalOf(data) };
  }
  function read(messageId) {
    return request({ path: "/messages/" + messageId + "/read", method: "PUT" });
  }
  function readAll() {
    return request({ path: "/messages/read-all", method: "PUT" });
  }
  const notifyStore = vue.reactive({
    /** @type {object[]} 由消息页写入；首页/我的页只读 unreadCount */
    list: [],
    unreadCount: 0,
    loaded: false,
    loading: false,
    error: ""
  });
  async function refreshUnread() {
    notifyStore.loading = true;
    notifyStore.error = "";
    try {
      const { total } = await unread();
      notifyStore.unreadCount = total;
      notifyStore.loaded = true;
    } catch (e) {
      notifyStore.error = e.message || "消息加载失败";
    } finally {
      notifyStore.loading = false;
    }
  }
  const ORDER_LABEL = { 1: "待确认", 2: "已确认", 3: "已取消", 4: "已完成", 5: "已过期" };
  const DEVICE_LABEL = { 1: "设备完好", 2: "设备损坏", 3: "缺失配件" };
  const TICKET_LABEL = { 1: "待处理", 2: "处理中", 3: "已完成" };
  const SPACE_TYPE_LABEL = { 1: "会议室", 2: "展厅", 3: "多功能厅", 4: "户外场地" };
  const LABELS = {
    order: ORDER_LABEL,
    device: DEVICE_LABEL,
    ticket: TICKET_LABEL,
    spaceType: SPACE_TYPE_LABEL
  };
  const ENUM_TAG = {
    // 5 已过期用 red 与「已取消」的 gray 区分：它不是用户主动的决定
    order: { 1: "purple", 2: "green", 3: "gray", 4: "blue", 5: "red" },
    device: { 1: "green", 2: "red", 3: "orange" },
    ticket: { 1: "blue", 2: "orange", 3: "green" }
  };
  const TEXT_TAG = {
    待确认: "purple",
    已确认: "green",
    已取消: "gray",
    已完成: "blue",
    待处理: "blue",
    处理中: "orange",
    可用: "green",
    停用: "gray",
    正常: "green",
    维修中: "orange",
    设备完好: "green",
    完好: "green",
    设备损坏: "red",
    损坏: "red",
    缺失配件: "orange",
    灯泡老化: "red",
    使用中: "orange",
    已被预约: "blue",
    空闲: "gray"
  };
  function pick(map, key) {
    if (key === void 0 || key === null || key === "")
      return void 0;
    return map[key];
  }
  function statusLabel(kind, value, text) {
    if (text)
      return String(text);
    if (typeof value === "string" && !/^\d+$/.test(value))
      return value;
    return pick(LABELS[kind], Number(value)) || "未知";
  }
  function statusTag(kind, value, text) {
    const label = statusLabel(kind, value, text);
    return TEXT_TAG[label] || pick(ENUM_TAG[kind], Number(value)) || "gray";
  }
  function spaceTypeLabel(value) {
    if (value === void 0 || value === null || value === "")
      return "未知类型";
    if (typeof value === "string" && !/^\d+$/.test(value))
      return value;
    return SPACE_TYPE_LABEL[Number(value)] || "未知类型";
  }
  const NOTIFY_ICON = {
    1: "✅",
    2: "🤖",
    3: "⚠️",
    预约提醒: "✅",
    预约成功: "✅",
    变更致歉: "🤖",
    故障告警: "⚠️"
  };
  function notifyIcon(type) {
    return NOTIFY_ICON[type] || "🔔";
  }
  function canCancelOrder(statusValue, statusText) {
    const label = statusLabel("order", statusValue, statusText);
    return label === "待确认" || label === "已确认";
  }
  function canCompleteOrder(statusValue, statusText) {
    return statusLabel("order", statusValue, statusText) === "已确认";
  }
  function canConfirmOrder(statusValue, statusText) {
    return statusLabel("order", statusValue, statusText) === "待确认";
  }
  async function spaces(params) {
    const data = await request({ path: "/resources/spaces", method: "GET", data: params });
    return { list: listOf(data), total: totalOf(data) };
  }
  async function devices(params) {
    const data = await request({ path: "/resources/devices", method: "GET", data: params });
    return { list: listOf(data), total: totalOf(data) };
  }
  function spaceBookings(spaceId, days = 30) {
    return request({
      path: `/resources/spaces/${spaceId}/booked`,
      method: "GET",
      data: { days }
    });
  }
  const nameMaps = vue.reactive({
    /** spaceId → 场地名 */
    spaces: {},
    /** deviceId → 设备名 */
    devices: {},
    /**
     * spaceId → 场地完整信息 { name, budget, capacity, location }
     *
     * 为什么要多存一份：场地**预算**只存在于 `space_resource.budget`，
     * `reserve_order` 表里**没有预算列**（已查真库确认）。所以预约页想显示预算，
     * 只能借道这里。注意语义——这是「场地自身的预算」，不是「本次预约的花费」。
     */
    spaceInfo: {},
    loaded: false,
    /** 上一次加载失败的原因，供页面按需提示（为空表示没失败过） */
    error: ""
  });
  let inflight = null;
  function ensureNameMaps() {
    if (nameMaps.loaded)
      return Promise.resolve(nameMaps);
    if (inflight)
      return inflight;
    inflight = Promise.all([spaces(), devices()]).then(([spaceRes, deviceRes]) => {
      const spaces2 = {};
      const spaceInfo = {};
      for (const s of spaceRes && spaceRes.list || []) {
        const id = s.spaceId !== void 0 ? s.spaceId : s.id;
        if (id === void 0 || id === null)
          continue;
        const name = s.spaceName || s.name || "";
        spaces2[id] = name;
        spaceInfo[id] = {
          name,
          // /resources/spaces 已返回 budget（后端 float(s.budget)，未填则为 0）
          budget: s.budget,
          capacity: s.capacity,
          location: s.location
        };
      }
      const devices2 = {};
      for (const d of deviceRes && deviceRes.list || []) {
        const id = d.deviceId !== void 0 ? d.deviceId : d.id;
        if (id !== void 0 && id !== null)
          devices2[id] = d.deviceName || d.name || "";
      }
      nameMaps.spaces = spaces2;
      nameMaps.spaceInfo = spaceInfo;
      nameMaps.devices = devices2;
      nameMaps.loaded = true;
      nameMaps.error = "";
      return nameMaps;
    }).catch((e) => {
      nameMaps.error = e && e.message || "资源名称加载失败";
      return nameMaps;
    }).finally(() => {
      inflight = null;
    });
    return inflight;
  }
  function spaceLabel(spaceId) {
    if (spaceId === void 0 || spaceId === null || spaceId === "")
      return "未关联场地";
    return nameMaps.spaces[spaceId] || "场地 #" + spaceId;
  }
  function deviceLabel(deviceIds) {
    const ids = deviceIds || [];
    if (!ids.length)
      return "无";
    const names = ids.map((id) => nameMaps.devices[id] || "#" + id);
    return names.length > 2 ? names.length + " 台设备" : names.join(" + ");
  }
  function spaceBudget(spaceId) {
    const info = nameMaps.spaceInfo[spaceId];
    if (!info)
      return null;
    const n = Number(info.budget);
    return isNaN(n) || n <= 0 ? null : n;
  }
  const PAGE_SIZE = 3;
  const _sfc_main$e = {
    __name: "index",
    setup(__props, { expose: __expose }) {
      __expose();
      const loading = vue.ref(true);
      const upcomingList = vue.ref([]);
      const loadError = vue.ref("");
      const visibleCount = vue.ref(PAGE_SIZE);
      const scrollMaxH = vue.ref(420);
      const greeting = vue.computed(() => {
        return userStore.loggedIn ? `你好，${displayName()} 👋` : "你好，访客 👋";
      });
      const roleLabel = vue.computed(() => userStore.loggedIn ? roleText() : "未登录");
      const shownUpcoming = vue.computed(() => upcomingList.value.slice(0, visibleCount.value));
      const hasMoreUpcoming = vue.computed(() => upcomingList.value.length > visibleCount.value);
      const moreCount = vue.computed(() => Math.max(0, upcomingList.value.length - visibleCount.value));
      function loadMoreUpcoming() {
        visibleCount.value += PAGE_SIZE;
      }
      function orderKey(o, i) {
        const id = orderId(o);
        return id === void 0 ? "i" + i : "o" + id;
      }
      const entries = vue.computed(() => [
        { key: "voice", icon: "🎙", tone: "", label: "语音预约", url: "/pages/voice/record" },
        { key: "space", icon: "📷", tone: "g2", label: "拍照识场", url: "/pages/space/recognize" },
        { key: "venues", icon: "🏢", tone: "g5", label: "场地一览", url: "/pages/space/list" },
        { key: "order", icon: "🗓", tone: "g3", label: "我的预约", tab: 1 },
        { key: "msg", icon: "🔔", tone: "g4", label: "消息通知", tab: 3, badge: notifyStore.unreadCount }
      ]);
      function linesOf(o) {
        if (!o)
          return [];
        const lines = [];
        const range = formatTimeRange(o.startTime, o.endTime);
        if (range)
          lines.push(range);
        const devices2 = deviceLabel(o.deviceIds);
        if (devices2 && devices2 !== "无")
          lines.push("含" + devices2);
        return lines;
      }
      function badgeText(n) {
        return n > 99 ? "99+" : String(n);
      }
      function pickUpcomingList(list2) {
        const now = Date.now();
        const alive = list2.filter((o) => {
          const label = statusLabel("order", orderStatus(o), orderStatusText(o));
          if (label === "已取消" || label === "已完成")
            return false;
          const end = parseDateTime(o.endTime);
          return !end || end.getTime() >= now;
        });
        alive.sort((a, b) => {
          const da = parseDateTime(a.startTime);
          const db = parseDateTime(b.startTime);
          return (da ? da.getTime() : 0) - (db ? db.getTime() : 0);
        });
        return alive;
      }
      async function load() {
        loading.value = true;
        try {
          if (!userStore.loggedIn) {
            upcomingList.value = [];
            loadError.value = "";
            return;
          }
          const { list: list2 } = await myOrders();
          upcomingList.value = pickUpcomingList(list2);
          visibleCount.value = PAGE_SIZE;
          loadError.value = "";
        } catch (e) {
          upcomingList.value = [];
          loadError.value = e && e.message || "预约加载失败";
        } finally {
          loading.value = false;
        }
        if (userStore.loggedIn)
          refreshUnread();
      }
      onShow(() => {
        ensureNameMaps();
        measureScroll();
        load();
      });
      function measureScroll() {
        try {
          const info = typeof uni.getWindowInfo === "function" ? uni.getWindowInfo() : uni.getSystemInfoSync();
          const h = info && info.windowHeight || 0;
          if (h > 0)
            scrollMaxH.value = Math.min(620, Math.max(300, Math.round(h * 0.4)));
        } catch (e) {
        }
      }
      function go(item) {
        if (item.tab !== void 0) {
          const tab = TABS[item.tab];
          if (tab)
            uni.reLaunch({ url: tab.path });
          return;
        }
        uni.navigateTo({ url: item.url });
      }
      function goLogin() {
        uni.navigateTo({ url: "/pages/login/index" });
      }
      function goVoice() {
        uni.navigateTo({ url: "/pages/voice/record" });
      }
      function goOrders() {
        uni.reLaunch({ url: TABS[1].path });
      }
      function openOrder(o) {
        const id = orderId(o);
        if (id === void 0)
          return;
        uni.navigateTo({ url: `/pages/order/detail?orderId=${id}` });
      }
      const __returned__ = { loading, upcomingList, loadError, PAGE_SIZE, visibleCount, scrollMaxH, greeting, roleLabel, shownUpcoming, hasMoreUpcoming, moreCount, loadMoreUpcoming, orderKey, entries, linesOf, badgeText, pickUpcomingList, load, measureScroll, go, goLogin, goVoice, goOrders, openOrder, ref: vue.ref, computed: vue.computed, get onShow() {
        return onShow;
      }, get myOrders() {
        return myOrders;
      }, get refreshUnread() {
        return refreshUnread;
      }, get notifyStore() {
        return notifyStore;
      }, get userStore() {
        return userStore;
      }, get displayName() {
        return displayName;
      }, get roleText() {
        return roleText;
      }, get statusLabel() {
        return statusLabel;
      }, get statusTag() {
        return statusTag;
      }, get ensureNameMaps() {
        return ensureNameMaps;
      }, get deviceLabel() {
        return deviceLabel;
      }, get spaceLabel() {
        return spaceLabel;
      }, get orderStatus() {
        return orderStatus;
      }, get orderStatusText() {
        return orderStatusText;
      }, get orderId() {
        return orderId;
      }, get formatTimeRange() {
        return formatTimeRange;
      }, get parseDateTime() {
        return parseDateTime;
      }, get TABS() {
        return TABS;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$d(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    const _component_mp_tab_bar = resolveEasycom(vue.resolveDynamicComponent("mp-tab-bar"), __easycom_1$1);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        big: "",
        title: $setup.greeting,
        right: $setup.roleLabel
      }, null, 8, ["title", "right"]),
      vue.createElementVNode("view", { class: "app-body" }, [
        vue.createElementVNode("view", { class: "ai-hero" }, [
          vue.createElementVNode("view", { class: "tt" }, [
            vue.createElementVNode("view", { class: "live" }),
            vue.createElementVNode("text", null, "AI 小助手已就绪")
          ]),
          vue.createElementVNode("text", { class: "dd" }, "直接说出需求，我会自动解析约束、检索场地、排冲突、出方案。")
        ]),
        vue.createElementVNode("view", { class: "mcard" }, [
          vue.createElementVNode("view", { class: "mtitle" }, "快捷入口"),
          vue.createElementVNode("view", { class: "grid4" }, [
            (vue.openBlock(true), vue.createElementBlock(
              vue.Fragment,
              null,
              vue.renderList($setup.entries, (item) => {
                return vue.openBlock(), vue.createElementBlock("view", {
                  key: item.key,
                  class: "cell",
                  "hover-class": "btn-on",
                  "hover-stay-time": 60,
                  onClick: ($event) => $setup.go(item)
                }, [
                  vue.createElementVNode(
                    "view",
                    {
                      class: vue.normalizeClass(["ic", item.tone])
                    },
                    [
                      vue.createElementVNode(
                        "text",
                        null,
                        vue.toDisplayString(item.icon),
                        1
                        /* TEXT */
                      ),
                      item.badge > 0 ? (vue.openBlock(), vue.createElementBlock(
                        "view",
                        {
                          key: 0,
                          class: "badge"
                        },
                        vue.toDisplayString($setup.badgeText(item.badge)),
                        1
                        /* TEXT */
                      )) : vue.createCommentVNode("v-if", true)
                    ],
                    2
                    /* CLASS */
                  ),
                  vue.createElementVNode(
                    "text",
                    null,
                    vue.toDisplayString(item.label),
                    1
                    /* TEXT */
                  )
                ], 8, ["onClick"]);
              }),
              128
              /* KEYED_FRAGMENT */
            ))
          ])
        ]),
        vue.createElementVNode("view", { class: "mcard" }, [
          vue.createElementVNode("view", { class: "mtitle" }, [
            vue.createElementVNode("text", null, "即将开始"),
            vue.createElementVNode("text", {
              class: "more",
              onClick: $setup.goOrders
            }, "全部 ›")
          ]),
          $setup.loading ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 0,
            class: "mtext"
          }, "加载中…")) : $setup.shownUpcoming.length ? (vue.openBlock(), vue.createElementBlock(
            vue.Fragment,
            { key: 1 },
            [
              vue.createElementVNode(
                "scroll-view",
                {
                  "scroll-y": "",
                  class: "upscroll",
                  style: vue.normalizeStyle({ maxHeight: $setup.scrollMaxH + "px" }),
                  "show-scrollbar": false
                },
                [
                  (vue.openBlock(true), vue.createElementBlock(
                    vue.Fragment,
                    null,
                    vue.renderList($setup.shownUpcoming, (o, i) => {
                      return vue.openBlock(), vue.createElementBlock("view", {
                        key: $setup.orderKey(o, i),
                        class: "upnext",
                        "hover-class": "btn-on",
                        "hover-stay-time": 60,
                        onClick: ($event) => $setup.openOrder(o)
                      }, [
                        vue.createElementVNode("view", { class: "bar" }),
                        vue.createElementVNode("view", { class: "bd" }, [
                          vue.createElementVNode(
                            "text",
                            { class: "tt" },
                            vue.toDisplayString($setup.spaceLabel(o.spaceId)),
                            1
                            /* TEXT */
                          ),
                          (vue.openBlock(true), vue.createElementBlock(
                            vue.Fragment,
                            null,
                            vue.renderList($setup.linesOf(o), (line, li) => {
                              return vue.openBlock(), vue.createElementBlock(
                                "text",
                                {
                                  key: li,
                                  class: "dd"
                                },
                                vue.toDisplayString(line),
                                1
                                /* TEXT */
                              );
                            }),
                            128
                            /* KEYED_FRAGMENT */
                          )),
                          vue.createElementVNode("view", { class: "tags" }, [
                            vue.createElementVNode(
                              "text",
                              {
                                class: vue.normalizeClass(["tag", $setup.statusTag("order", $setup.orderStatus(o), $setup.orderStatusText(o))])
                              },
                              vue.toDisplayString($setup.statusLabel("order", $setup.orderStatus(o), $setup.orderStatusText(o))),
                              3
                              /* TEXT, CLASS */
                            )
                          ])
                        ])
                      ], 8, ["onClick"]);
                    }),
                    128
                    /* KEYED_FRAGMENT */
                  ))
                ],
                4
                /* STYLE */
              ),
              $setup.hasMoreUpcoming ? (vue.openBlock(), vue.createElementBlock(
                "view",
                {
                  key: 0,
                  class: "upmore",
                  "hover-class": "btn-on",
                  "hover-stay-time": 60,
                  onClick: $setup.loadMoreUpcoming
                },
                "加载更多（还有 " + vue.toDisplayString($setup.moreCount) + " 条）",
                1
                /* TEXT */
              )) : vue.createCommentVNode("v-if", true)
            ],
            64
            /* STABLE_FRAGMENT */
          )) : !$setup.userStore.loggedIn ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 2,
            class: "mini-empty"
          }, [
            vue.createElementVNode("text", { class: "ei" }, "🔑"),
            vue.createElementVNode("text", { class: "et" }, "登录后查看你的预约"),
            vue.createElementVNode("view", {
              class: "btn ai",
              "hover-class": "btn-on",
              onClick: $setup.goLogin
            }, "去登录")
          ])) : $setup.loadError ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 3,
            class: "mini-empty"
          }, [
            vue.createElementVNode("text", { class: "ei" }, "⚠️"),
            vue.createElementVNode(
              "text",
              { class: "et" },
              vue.toDisplayString($setup.loadError),
              1
              /* TEXT */
            ),
            vue.createElementVNode("view", {
              class: "btn ghost",
              "hover-class": "btn-on",
              onClick: $setup.load
            }, "重试")
          ])) : (vue.openBlock(), vue.createElementBlock("view", {
            key: 4,
            class: "mini-empty"
          }, [
            vue.createElementVNode("text", { class: "ei" }, "🗓"),
            vue.createElementVNode("text", { class: "et" }, "暂无即将开始的预约"),
            vue.createElementVNode("view", {
              class: "btn ai",
              "hover-class": "btn-on",
              onClick: $setup.goVoice
            }, "语音预约一场")
          ]))
        ])
      ]),
      vue.createVNode(_component_mp_tab_bar, { current: 0 })
    ]);
  }
  const PagesIndexIndex = /* @__PURE__ */ _export_sfc(_sfc_main$e, [["render", _sfc_render$d], ["__scopeId", "data-v-1cf27b2a"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/index/index.vue"]]);
  const _sfc_main$d = {
    __name: "mp-empty",
    props: {
      icon: { type: String, default: "📭" },
      text: { type: String, default: "暂无数据" },
      /** 传了才渲染操作按钮 */
      actionText: { type: String, default: "" }
    },
    emits: ["action"],
    setup(__props, { expose: __expose }) {
      __expose();
      const __returned__ = {};
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$c(_ctx, _cache, $props, $setup, $data, $options) {
    return vue.openBlock(), vue.createElementBlock("view", { class: "empty" }, [
      vue.createElementVNode(
        "text",
        { class: "icon" },
        vue.toDisplayString($props.icon),
        1
        /* TEXT */
      ),
      vue.createElementVNode(
        "text",
        { class: "txt" },
        vue.toDisplayString($props.text),
        1
        /* TEXT */
      ),
      $props.actionText ? (vue.openBlock(), vue.createElementBlock(
        "view",
        {
          key: 0,
          class: "act",
          "hover-class": "act-on",
          "hover-stay-time": 60,
          onClick: _cache[0] || (_cache[0] = ($event) => _ctx.$emit("action"))
        },
        vue.toDisplayString($props.actionText),
        1
        /* TEXT */
      )) : vue.createCommentVNode("v-if", true)
    ]);
  }
  const __easycom_1 = /* @__PURE__ */ _export_sfc(_sfc_main$d, [["render", _sfc_render$c], ["__scopeId", "data-v-7423a8c1"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/components/mp-empty/mp-empty.vue"]]);
  const _sfc_main$c = {
    __name: "list",
    setup(__props, { expose: __expose }) {
      __expose();
      const SEGMENTS = [
        { key: "all", label: "全部" },
        { key: "待确认", label: "待确认" },
        { key: "已确认", label: "已确认" },
        { key: "已完成", label: "已完成" }
      ];
      const list2 = vue.ref([]);
      const loading = vue.ref(true);
      const error = vue.ref("");
      const seg = vue.ref("all");
      function labelOf(o) {
        return statusLabel("order", orderStatus(o), orderStatusText(o));
      }
      const shown = vue.computed(() => {
        if (seg.value === "all")
          return list2.value;
        return list2.value.filter((o) => labelOf(o) === seg.value);
      });
      function countOf(key) {
        return list2.value.filter((o) => labelOf(o) === key).length;
      }
      function orderNoOf(o) {
        const id = orderId(o);
        return id === void 0 ? "—" : "#" + id;
      }
      function budgetOf(o) {
        return formatMoney(spaceBudget(o && o.spaceId)) || "—";
      }
      function rangeOf(o) {
        return formatTimeRange(o.startTime, o.endTime) || "—";
      }
      async function load() {
        loading.value = true;
        error.value = "";
        try {
          const res = await myOrders({ page: 1, pageSize: 50 });
          list2.value = res.list;
        } catch (e) {
          error.value = e.message || "预约加载失败";
          list2.value = [];
        } finally {
          loading.value = false;
        }
      }
      onShow(() => {
        ensureNameMaps();
        load();
      });
      async function askCancel(o) {
        const ok = await confirm({
          title: "取消预约",
          content: `确定取消「${spaceLabel(o.spaceId)}」的预约吗？取消后时段将释放给其他人。`,
          confirmText: "确定取消",
          confirmColor: "#F56C6C"
        });
        if (!ok)
          return;
        const id = orderId(o);
        if (id === void 0) {
          toast("这条预约缺少单号，无法取消");
          return;
        }
        try {
          await cancelOrder(id);
          toastOk("已取消");
          load();
        } catch (e) {
          toast(e.message || "取消失败");
          load();
        }
      }
      async function askConfirm(o) {
        const ok = await confirm({
          title: "确认预约",
          content: `确认「${spaceLabel(o.spaceId)}」这场预约吗？确认后该时段正式占用。`,
          confirmText: "确认预约"
        });
        if (!ok)
          return;
        const id = orderId(o);
        if (id === void 0) {
          toast("这条预约缺少单号，无法确认");
          return;
        }
        try {
          await confirmOrder(id);
          toastOk("已确认");
          load();
        } catch (e) {
          toast(e.message || "确认失败");
          load();
        }
      }
      async function askComplete(o) {
        const ok = await confirm({
          title: "标记完成",
          content: `确认「${spaceLabel(o.spaceId)}」这场预约已经结束了吗？完成后该时段会释放给其他人。`,
          confirmText: "标记完成"
        });
        if (!ok)
          return;
        const id = orderId(o);
        if (id === void 0) {
          toast("这条预约缺少单号，无法标记完成");
          return;
        }
        try {
          await completeOrder(id);
          toastOk("已完成");
          load();
        } catch (e) {
          toast(e.message || "操作失败");
          load();
        }
      }
      function openDetail(o) {
        const id = orderId(o);
        if (id === void 0)
          return;
        uni.navigateTo({ url: `/pages/order/detail?orderId=${id}` });
      }
      function goVoice() {
        uni.navigateTo({ url: "/pages/voice/record" });
      }
      const __returned__ = { SEGMENTS, list: list2, loading, error, seg, labelOf, shown, countOf, orderNoOf, budgetOf, rangeOf, load, askCancel, askConfirm, askComplete, openDetail, goVoice, ref: vue.ref, computed: vue.computed, get onShow() {
        return onShow;
      }, get myOrders() {
        return myOrders;
      }, get cancelOrder() {
        return cancelOrder;
      }, get completeOrder() {
        return completeOrder;
      }, get confirmOrder() {
        return confirmOrder;
      }, get statusLabel() {
        return statusLabel;
      }, get statusTag() {
        return statusTag;
      }, get canCancelOrder() {
        return canCancelOrder;
      }, get canCompleteOrder() {
        return canCompleteOrder;
      }, get canConfirmOrder() {
        return canConfirmOrder;
      }, get ensureNameMaps() {
        return ensureNameMaps;
      }, get deviceLabel() {
        return deviceLabel;
      }, get spaceLabel() {
        return spaceLabel;
      }, get spaceBudget() {
        return spaceBudget;
      }, get orderStatus() {
        return orderStatus;
      }, get orderStatusText() {
        return orderStatusText;
      }, get orderId() {
        return orderId;
      }, get formatTimeRange() {
        return formatTimeRange;
      }, get formatMoney() {
        return formatMoney;
      }, get confirm() {
        return confirm;
      }, get toastOk() {
        return toastOk;
      }, get toast() {
        return toast;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$b(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    const _component_mp_empty = resolveEasycom(vue.resolveDynamicComponent("mp-empty"), __easycom_1);
    const _component_mp_tab_bar = resolveEasycom(vue.resolveDynamicComponent("mp-tab-bar"), __easycom_1$1);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, { title: "我的预约" }),
      vue.createElementVNode("view", { class: "app-body" }, [
        vue.createElementVNode("view", { class: "segs" }, [
          (vue.openBlock(), vue.createElementBlock(
            vue.Fragment,
            null,
            vue.renderList($setup.SEGMENTS, (s) => {
              return vue.createElementVNode("view", {
                key: s.key,
                class: vue.normalizeClass(["seg", { on: $setup.seg === s.key }]),
                onClick: ($event) => $setup.seg = s.key
              }, [
                vue.createElementVNode(
                  "text",
                  null,
                  vue.toDisplayString(s.label),
                  1
                  /* TEXT */
                ),
                s.key !== "all" && $setup.countOf(s.key) > 0 ? (vue.openBlock(), vue.createElementBlock(
                  "text",
                  {
                    key: 0,
                    class: "n"
                  },
                  vue.toDisplayString($setup.countOf(s.key)),
                  1
                  /* TEXT */
                )) : vue.createCommentVNode("v-if", true)
              ], 10, ["onClick"]);
            }),
            64
            /* STABLE_FRAGMENT */
          ))
        ]),
        $setup.loading ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 0,
          class: "mcard"
        }, [
          vue.createElementVNode("text", { class: "mtext" }, "加载中…")
        ])) : $setup.error ? (vue.openBlock(), vue.createBlock(_component_mp_empty, {
          key: 1,
          icon: "⚠️",
          text: $setup.error,
          "action-text": "重试",
          onAction: $setup.load
        }, null, 8, ["text"])) : !$setup.shown.length ? (vue.openBlock(), vue.createBlock(_component_mp_empty, {
          key: 2,
          icon: "🗓",
          text: "这里还没有预约",
          "action-text": "去语音预约",
          onAction: $setup.goVoice
        })) : (vue.openBlock(), vue.createElementBlock("view", { key: 3 }, [
          (vue.openBlock(true), vue.createElementBlock(
            vue.Fragment,
            null,
            vue.renderList($setup.shown, (o) => {
              return vue.openBlock(), vue.createElementBlock("view", {
                key: $setup.orderId(o),
                class: "mcard",
                "hover-class": "btn-on",
                "hover-stay-time": 60,
                onClick: ($event) => $setup.openDetail(o)
              }, [
                vue.createElementVNode("view", { class: "ohead" }, [
                  vue.createElementVNode(
                    "text",
                    { class: "oname" },
                    vue.toDisplayString($setup.spaceLabel(o.spaceId)),
                    1
                    /* TEXT */
                  ),
                  vue.createElementVNode(
                    "text",
                    {
                      class: vue.normalizeClass(["tag", $setup.statusTag("order", $setup.orderStatus(o), $setup.orderStatusText(o))])
                    },
                    vue.toDisplayString($setup.statusLabel("order", $setup.orderStatus(o), $setup.orderStatusText(o))),
                    3
                    /* TEXT, CLASS */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "时段"),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString($setup.rangeOf(o)),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "设备"),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString($setup.deviceLabel(o.deviceIds)),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "场地预算"),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString($setup.budgetOf(o)),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "单号"),
                  vue.createElementVNode(
                    "text",
                    { class: "v mono" },
                    vue.toDisplayString($setup.orderNoOf(o)),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "oa" }, [
                  $setup.canConfirmOrder($setup.orderStatus(o), $setup.orderStatusText(o)) ? (vue.openBlock(), vue.createElementBlock("view", {
                    key: 0,
                    class: "btn",
                    "hover-class": "btn-on",
                    "hover-stay-time": 60,
                    onClick: vue.withModifiers(($event) => $setup.askConfirm(o), ["stop"])
                  }, "确认预约", 8, ["onClick"])) : vue.createCommentVNode("v-if", true),
                  $setup.canCompleteOrder($setup.orderStatus(o), $setup.orderStatusText(o)) ? (vue.openBlock(), vue.createElementBlock("view", {
                    key: 1,
                    class: "btn ghost",
                    "hover-class": "btn-on",
                    "hover-stay-time": 60,
                    onClick: vue.withModifiers(($event) => $setup.askComplete(o), ["stop"])
                  }, "标记完成", 8, ["onClick"])) : vue.createCommentVNode("v-if", true),
                  $setup.canCancelOrder($setup.orderStatus(o), $setup.orderStatusText(o)) ? (vue.openBlock(), vue.createElementBlock("view", {
                    key: 2,
                    class: "btn ghost",
                    "hover-class": "btn-on",
                    "hover-stay-time": 60,
                    onClick: vue.withModifiers(($event) => $setup.askCancel(o), ["stop"])
                  }, "取消预约", 8, ["onClick"])) : vue.createCommentVNode("v-if", true)
                ])
              ], 8, ["onClick"]);
            }),
            128
            /* KEYED_FRAGMENT */
          ))
        ]))
      ]),
      vue.createVNode(_component_mp_tab_bar, { current: 1 })
    ]);
  }
  const PagesOrderList = /* @__PURE__ */ _export_sfc(_sfc_main$c, [["render", _sfc_render$b], ["__scopeId", "data-v-456ecf67"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/order/list.vue"]]);
  function submit(filePath, spaceId) {
    const formData = {};
    if (spaceId !== void 0 && spaceId !== null && spaceId !== "") {
      formData.spaceId = String(spaceId);
    }
    return upload({ path: "/inspect/submit", filePath, name: "file", formData, silent: true });
  }
  async function tickets(params) {
    const data = await request({ path: "/tickets/list", method: "GET", data: params });
    return { list: listOf(data), total: totalOf(data) };
  }
  function updateTicketStatus(ticketId, status) {
    return request({ path: `/tickets/${ticketId}/status`, method: "PUT", data: { status } });
  }
  function handleTicket(ticketId, filePath) {
    return upload({ path: `/tickets/${ticketId}/handle`, filePath, name: "file" });
  }
  const _sfc_main$b = {
    __name: "index",
    setup(__props, { expose: __expose }) {
      __expose();
      const tickets$1 = vue.ref([]);
      const loading = vue.ref(true);
      async function load() {
        if (!userStore.loggedIn) {
          tickets$1.value = [];
          loading.value = false;
          return;
        }
        loading.value = true;
        try {
          const res = await tickets({ page: 1, pageSize: 50 });
          tickets$1.value = res.list;
        } catch (e) {
          tickets$1.value = [];
          toast(e.message || "工单加载失败");
        } finally {
          loading.value = false;
        }
      }
      onShow(() => {
        ensureNameMaps();
        load();
      });
      function canFinish(t) {
        const label = statusLabel("ticket", t.status, t.statusText);
        return label === "待处理" || label === "处理中";
      }
      async function finish(t) {
        const ok = await confirm({
          content: `确认工单 #${t.id}（${t.deviceName || "设备"}）已处理完成？`,
          title: "标记完成",
          confirmText: "确认完成"
        });
        if (!ok)
          return;
        try {
          await updateTicketStatus(t.id, 3);
          toastOk("工单已完成");
          load();
        } catch (e) {
          toast(e.message || "操作失败");
        }
      }
      async function verifyWithPhoto(t) {
        const picked = await chooseImage();
        if (!picked)
          return;
        showLoading("AI 核验中…");
        try {
          const res = await handleTicket(t.id, picked);
          hideLoading();
          if (res && res.passed) {
            toastOk("核验通过，工单已完成");
          } else {
            const why = res && res.verifyReport || "AI 核验未通过";
            uni.showModal({
              title: "核验未通过",
              content: `${why}

工单状态未变更，可以重拍一张更清晰的照片再试。`,
              showCancel: false,
              confirmText: "知道了"
            });
          }
          load();
        } catch (e) {
          hideLoading();
          toast(e && e.message || "核验失败");
          load();
        }
      }
      function chooseImage() {
        return new Promise((resolve) => {
          uni.chooseImage({
            count: 1,
            sizeType: ["compressed"],
            sourceType: ["camera", "album"],
            success: (res) => {
              const files = res.tempFilePaths || [];
              resolve(files[0] || null);
            },
            fail: () => resolve(null)
          });
        });
      }
      function goCapture() {
        uni.navigateTo({ url: "/pages/inspect/capture" });
      }
      const __returned__ = { tickets: tickets$1, loading, load, canFinish, finish, verifyWithPhoto, chooseImage, goCapture, ref: vue.ref, get onShow() {
        return onShow;
      }, get fetchTickets() {
        return tickets;
      }, get updateTicketStatus() {
        return updateTicketStatus;
      }, get handleTicket() {
        return handleTicket;
      }, get userStore() {
        return userStore;
      }, get isAdmin() {
        return isAdmin;
      }, get statusLabel() {
        return statusLabel;
      }, get statusTag() {
        return statusTag;
      }, get ensureNameMaps() {
        return ensureNameMaps;
      }, get spaceLabel() {
        return spaceLabel;
      }, get toast() {
        return toast;
      }, get toastOk() {
        return toastOk;
      }, get confirm() {
        return confirm;
      }, get showLoading() {
        return showLoading;
      }, get hideLoading() {
        return hideLoading;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$a(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    const _component_mp_tab_bar = resolveEasycom(vue.resolveDynamicComponent("mp-tab-bar"), __easycom_1$1);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, { title: "AI 智能巡检" }),
      vue.createElementVNode("view", { class: "app-body" }, [
        !$setup.isAdmin() ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 0,
          class: "mini-empty",
          style: { "padding-top": "140rpx" }
        }, [
          vue.createElementVNode("text", { class: "ei" }, "🔒"),
          vue.createElementVNode("text", { class: "et" }, "仅管理员账号可查看巡检内容")
        ])) : (vue.openBlock(), vue.createElementBlock(
          vue.Fragment,
          { key: 1 },
          [
            vue.createElementVNode("view", {
              class: "imgbox entry",
              "hover-class": "btn-on",
              "hover-stay-time": 60,
              onClick: $setup.goCapture
            }, [
              vue.createElementVNode("view", { class: "cam" }, [
                vue.createElementVNode("text", { class: "big" }, "📷"),
                vue.createElementVNode("text", null, "拍下设备，AI 自动识别状态并生成工单")
              ]),
              vue.createElementVNode("view", { class: "bbox" }, [
                vue.createElementVNode("view", { class: "cn" }),
                vue.createElementVNode("view", { class: "cn" }),
                vue.createElementVNode("view", { class: "cn" }),
                vue.createElementVNode("view", { class: "cn" }),
                vue.createElementVNode("text", { class: "lbl" }, "对准设备")
              ]),
              vue.createElementVNode("view", { class: "scanline" })
            ]),
            vue.createElementVNode("view", { class: "mcard sec" }, [
              vue.createElementVNode("view", { class: "mtitle" }, [
                vue.createElementVNode("text", null, "维修工单"),
                vue.createElementVNode(
                  "text",
                  {
                    class: "more",
                    onClick: $setup.load
                  },
                  vue.toDisplayString($setup.loading ? "刷新中…" : "刷新"),
                  1
                  /* TEXT */
                )
              ]),
              $setup.loading ? (vue.openBlock(), vue.createElementBlock("text", {
                key: 0,
                class: "mtext"
              }, "加载中…")) : !$setup.userStore.loggedIn ? (vue.openBlock(), vue.createElementBlock("view", {
                key: 1,
                class: "mini-empty"
              }, [
                vue.createElementVNode("text", { class: "ei" }, "🔑"),
                vue.createElementVNode("text", { class: "et" }, "登录后查看维修工单")
              ])) : !$setup.tickets.length ? (vue.openBlock(), vue.createElementBlock("view", {
                key: 2,
                class: "mini-empty"
              }, [
                vue.createElementVNode("text", { class: "ei" }, "🧰"),
                vue.createElementVNode("text", { class: "et" }, "暂无维修工单，设备一切正常")
              ])) : (vue.openBlock(), vue.createElementBlock("view", { key: 3 }, [
                (vue.openBlock(true), vue.createElementBlock(
                  vue.Fragment,
                  null,
                  vue.renderList($setup.tickets, (t, i) => {
                    return vue.openBlock(), vue.createElementBlock(
                      "view",
                      {
                        key: t.id,
                        class: vue.normalizeClass(["ticket", { sep: i > 0 }])
                      },
                      [
                        vue.createElementVNode("view", { class: "thead" }, [
                          vue.createElementVNode(
                            "text",
                            { class: "tname" },
                            vue.toDisplayString(t.deviceName || "未知设备"),
                            1
                            /* TEXT */
                          ),
                          vue.createElementVNode(
                            "text",
                            {
                              class: vue.normalizeClass(["tag", $setup.statusTag("ticket", t.status, t.statusText)])
                            },
                            vue.toDisplayString($setup.statusLabel("ticket", t.status, t.statusText)),
                            3
                            /* TEXT, CLASS */
                          )
                        ]),
                        vue.createElementVNode(
                          "text",
                          { class: "tno" },
                          "工单 #" + vue.toDisplayString(t.id) + " · " + vue.toDisplayString($setup.spaceLabel(t.spaceId)),
                          1
                          /* TEXT */
                        ),
                        t.report ? (vue.openBlock(), vue.createElementBlock(
                          "text",
                          {
                            key: 0,
                            class: "tdesc"
                          },
                          vue.toDisplayString(t.report),
                          1
                          /* TEXT */
                        )) : vue.createCommentVNode("v-if", true),
                        vue.createElementVNode("view", { class: "tfoot" }, [
                          $setup.canFinish(t) ? (vue.openBlock(), vue.createElementBlock("view", {
                            key: 0,
                            class: "btn ai tiny",
                            "hover-class": "btn-on",
                            "hover-stay-time": 60,
                            onClick: vue.withModifiers(($event) => $setup.verifyWithPhoto(t), ["stop"])
                          }, "拍照核验", 8, ["onClick"])) : vue.createCommentVNode("v-if", true),
                          $setup.canFinish(t) ? (vue.openBlock(), vue.createElementBlock("view", {
                            key: 1,
                            class: "btn ghost tiny",
                            "hover-class": "btn-on",
                            "hover-stay-time": 60,
                            onClick: vue.withModifiers(($event) => $setup.finish(t), ["stop"])
                          }, "标记完成", 8, ["onClick"])) : vue.createCommentVNode("v-if", true)
                        ])
                      ],
                      2
                      /* CLASS */
                    );
                  }),
                  128
                  /* KEYED_FRAGMENT */
                ))
              ]))
            ])
          ],
          64
          /* STABLE_FRAGMENT */
        ))
      ]),
      vue.createVNode(_component_mp_tab_bar, { current: 2 })
    ]);
  }
  const PagesInspectIndex = /* @__PURE__ */ _export_sfc(_sfc_main$b, [["render", _sfc_render$a], ["__scopeId", "data-v-47b0dedd"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/inspect/index.vue"]]);
  const _sfc_main$a = {
    __name: "list",
    setup(__props, { expose: __expose }) {
      __expose();
      const list$1 = vue.ref([]);
      const loading = vue.ref(true);
      const error = vue.ref("");
      function iconKey(m) {
        return m.notifyType !== void 0 && m.notifyType !== null ? m.notifyType : m.title;
      }
      function syncUnreadCount() {
        notifyStore.unreadCount = list$1.value.filter((m) => !m.isRead).length;
      }
      async function load() {
        if (!userStore.loggedIn) {
          list$1.value = [];
          error.value = "";
          loading.value = false;
          return;
        }
        loading.value = true;
        error.value = "";
        try {
          const res = await list({ skip: 0, limit: 50 });
          list$1.value = res.list;
          notifyStore.list = res.list;
          syncUnreadCount();
        } catch (e) {
          error.value = e.message || "消息加载失败";
          list$1.value = [];
        } finally {
          loading.value = false;
        }
      }
      function goLogin() {
        uni.navigateTo({ url: "/pages/login/index" });
      }
      onShow(load);
      async function readAll$1() {
        const unreadCount = list$1.value.filter((m) => !m.isRead).length;
        if (!unreadCount) {
          toast("没有未读消息");
          return;
        }
        try {
          await readAll();
        } catch (e) {
          toast(e.message || "标记失败，请重试");
          await load();
          return;
        }
        list$1.value = list$1.value.map((m) => ({ ...m, isRead: true }));
        syncUnreadCount();
        toastOk("已全部标为已读");
      }
      async function openMsg(m) {
        if (m.isRead)
          return;
        try {
          await read(m.messageId);
        } catch (e) {
          toast(e.message || "标记已读失败");
          return;
        }
        m.isRead = true;
        syncUnreadCount();
      }
      const __returned__ = { list: list$1, loading, error, iconKey, syncUnreadCount, load, goLogin, readAll: readAll$1, openMsg, ref: vue.ref, get onShow() {
        return onShow;
      }, get fetchMessages() {
        return list;
      }, get read() {
        return read;
      }, get readAllApi() {
        return readAll;
      }, get notifyStore() {
        return notifyStore;
      }, get userStore() {
        return userStore;
      }, get notifyIcon() {
        return notifyIcon;
      }, get relativeTime() {
        return relativeTime;
      }, get toastOk() {
        return toastOk;
      }, get toast() {
        return toast;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$9(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    const _component_mp_empty = resolveEasycom(vue.resolveDynamicComponent("mp-empty"), __easycom_1);
    const _component_mp_tab_bar = resolveEasycom(vue.resolveDynamicComponent("mp-tab-bar"), __easycom_1$1);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "消息通知",
        right: "全部已读",
        onRight: $setup.readAll
      }),
      vue.createElementVNode("view", { class: "app-body" }, [
        $setup.loading ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 0,
          class: "mcard"
        }, [
          vue.createElementVNode("text", { class: "mtext" }, "加载中…")
        ])) : $setup.error ? (vue.openBlock(), vue.createBlock(_component_mp_empty, {
          key: 1,
          icon: "⚠️",
          text: $setup.error,
          "action-text": "重试",
          onAction: $setup.load
        }, null, 8, ["text"])) : !$setup.userStore.loggedIn ? (vue.openBlock(), vue.createBlock(_component_mp_empty, {
          key: 2,
          icon: "🔑",
          text: "登录后查看消息通知",
          "action-text": "去登录",
          onAction: $setup.goLogin
        })) : !$setup.list.length ? (vue.openBlock(), vue.createBlock(_component_mp_empty, {
          key: 3,
          icon: "🔔",
          text: "暂无消息",
          "action-text": "刷新",
          onAction: $setup.load
        })) : (vue.openBlock(), vue.createElementBlock("view", { key: 4 }, [
          (vue.openBlock(true), vue.createElementBlock(
            vue.Fragment,
            null,
            vue.renderList($setup.list, (m) => {
              return vue.openBlock(), vue.createElementBlock("view", {
                key: m.messageId,
                class: vue.normalizeClass(["msg", { unread: !m.isRead }]),
                onClick: ($event) => $setup.openMsg(m)
              }, [
                vue.createElementVNode("view", { class: "h" }, [
                  vue.createElementVNode(
                    "text",
                    null,
                    vue.toDisplayString($setup.notifyIcon($setup.iconKey(m))) + " " + vue.toDisplayString(m.title || "通知"),
                    1
                    /* TEXT */
                  ),
                  vue.createElementVNode(
                    "text",
                    { class: "t" },
                    vue.toDisplayString($setup.relativeTime(m.createTime)),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode(
                  "text",
                  {
                    class: "txt",
                    "user-select": true
                  },
                  vue.toDisplayString(m.content),
                  1
                  /* TEXT */
                )
              ], 10, ["onClick"]);
            }),
            128
            /* KEYED_FRAGMENT */
          ))
        ]))
      ]),
      vue.createVNode(_component_mp_tab_bar, { current: 3 })
    ]);
  }
  const PagesMessageList = /* @__PURE__ */ _export_sfc(_sfc_main$a, [["render", _sfc_render$9], ["__scopeId", "data-v-904eb306"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/message/list.vue"]]);
  const _sfc_main$9 = {
    __name: "index",
    setup(__props, { expose: __expose }) {
      __expose();
      const orderCount = vue.ref(0);
      const ticketCount = vue.ref(0);
      const userId = vue.computed(() => {
        if (!userStore.info)
          return "—";
        return userStore.info.id === void 0 || userStore.info.id === null ? "—" : String(userStore.info.id);
      });
      const avatarEmoji = vue.computed(() => {
        if (!userStore.loggedIn)
          return "👤";
        return userStore.role === "admin" ? "🧑💼" : userStore.role === "resource_admin" ? "🧰" : "🙂";
      });
      const stats = vue.computed(() => [
        { key: "order", label: "我的预约", value: fmtCount(orderCount.value), tab: 1 },
        { key: "ticket", label: "维修工单", value: fmtCount(ticketCount.value), tab: 2 },
        { key: "msg", label: "未读消息", value: fmtCount(notifyStore.unreadCount), tab: 3 }
      ]);
      function fmtCount(v) {
        return v === null || v === void 0 ? "—" : v;
      }
      const menus = vue.computed(() => [
        { key: "voice", icon: "🎙", label: "语音预约", url: "/pages/voice/record" },
        { key: "space", icon: "📷", label: "拍照识场", url: "/pages/space/recognize" },
        { key: "capture", icon: "🧰", label: "拍照巡检", url: "/pages/inspect/capture" },
        { key: "order", icon: "🗓", label: "我的预约", tab: 1 },
        { key: "msg", icon: "🔔", label: "消息通知", tab: 3, badge: notifyStore.unreadCount }
      ]);
      const apiModeText = vue.computed(
        () => "真实接口（/api/v1/*）"
      );
      async function load() {
        if (!userStore.loggedIn) {
          orderCount.value = 0;
          ticketCount.value = 0;
          return;
        }
        try {
          const res = await myOrders();
          orderCount.value = res.total;
        } catch (e) {
          orderCount.value = null;
        }
        try {
          const res = await tickets();
          ticketCount.value = res.total;
        } catch (e) {
          ticketCount.value = null;
        }
        refreshUnread();
      }
      onShow(load);
      function go(item) {
        if (item.tab !== void 0) {
          const tab = TABS[item.tab];
          if (tab)
            uni.reLaunch({ url: tab.path });
          return;
        }
        if (item.url)
          uni.navigateTo({ url: item.url });
      }
      function goLogin() {
        uni.navigateTo({ url: "/pages/login/index" });
      }
      async function askLogout() {
        const ok = await confirm({
          content: "退出后需要重新登录才能查看预约与工单。",
          title: "退出登录",
          confirmText: "退出",
          confirmColor: "#F56C6C"
        });
        if (!ok)
          return;
        await doLogout();
        toastOk("已退出登录");
        orderCount.value = 0;
        ticketCount.value = 0;
        notifyStore.list = [];
        notifyStore.unreadCount = 0;
      }
      const __returned__ = { orderCount, ticketCount, userId, avatarEmoji, stats, fmtCount, menus, apiModeText, load, go, goLogin, askLogout, ref: vue.ref, computed: vue.computed, get onShow() {
        return onShow;
      }, get userStore() {
        return userStore;
      }, get displayName() {
        return displayName;
      }, get roleText() {
        return roleText;
      }, get doLogout() {
        return doLogout;
      }, get notifyStore() {
        return notifyStore;
      }, get refreshUnread() {
        return refreshUnread;
      }, get myOrders() {
        return myOrders;
      }, get fetchTickets() {
        return tickets;
      }, get API_MODE() {
        return API_MODE;
      }, get toastOk() {
        return toastOk;
      }, get confirm() {
        return confirm;
      }, get TABS() {
        return TABS;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$8(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    const _component_mp_tab_bar = resolveEasycom(vue.resolveDynamicComponent("mp-tab-bar"), __easycom_1$1);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        big: "",
        title: "我的",
        right: $setup.userStore.loggedIn ? $setup.roleText() : ""
      }, null, 8, ["right"]),
      vue.createElementVNode("view", { class: "app-body" }, [
        vue.createElementVNode("view", { class: "mcard prof" }, [
          vue.createElementVNode(
            "view",
            { class: "avatar" },
            vue.toDisplayString($setup.avatarEmoji),
            1
            /* TEXT */
          ),
          vue.createElementVNode("view", { class: "pinfo" }, [
            vue.createElementVNode(
              "text",
              { class: "pname" },
              vue.toDisplayString($setup.userStore.loggedIn ? $setup.displayName() : "未登录"),
              1
              /* TEXT */
            ),
            vue.createElementVNode(
              "text",
              { class: "prole" },
              vue.toDisplayString($setup.userStore.loggedIn ? `账号 ID：${$setup.userId}` : "登录后可查看预约与工单"),
              1
              /* TEXT */
            )
          ]),
          !$setup.userStore.loggedIn ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 0,
            class: "btn",
            "hover-class": "btn-on",
            "hover-stay-time": 60,
            onClick: $setup.goLogin
          }, "去登录")) : vue.createCommentVNode("v-if", true)
        ]),
        vue.createElementVNode("view", { class: "stats" }, [
          (vue.openBlock(true), vue.createElementBlock(
            vue.Fragment,
            null,
            vue.renderList($setup.stats, (s) => {
              return vue.openBlock(), vue.createElementBlock("view", {
                key: s.key,
                class: "stat",
                onClick: ($event) => $setup.go(s)
              }, [
                vue.createElementVNode(
                  "text",
                  { class: "num" },
                  vue.toDisplayString(s.value),
                  1
                  /* TEXT */
                ),
                vue.createElementVNode(
                  "text",
                  { class: "lb" },
                  vue.toDisplayString(s.label),
                  1
                  /* TEXT */
                )
              ], 8, ["onClick"]);
            }),
            128
            /* KEYED_FRAGMENT */
          ))
        ]),
        vue.createElementVNode("view", { class: "mcard" }, [
          vue.createElementVNode("view", { class: "mtitle" }, "常用功能"),
          (vue.openBlock(true), vue.createElementBlock(
            vue.Fragment,
            null,
            vue.renderList($setup.menus, (m, i) => {
              return vue.openBlock(), vue.createElementBlock("view", {
                key: m.key,
                class: vue.normalizeClass(["mrow", { sep: i > 0 }]),
                "hover-class": "btn-on",
                "hover-stay-time": 60,
                onClick: ($event) => $setup.go(m)
              }, [
                vue.createElementVNode(
                  "text",
                  { class: "mi" },
                  vue.toDisplayString(m.icon),
                  1
                  /* TEXT */
                ),
                vue.createElementVNode(
                  "text",
                  { class: "ml" },
                  vue.toDisplayString(m.label),
                  1
                  /* TEXT */
                ),
                m.badge > 0 ? (vue.openBlock(), vue.createElementBlock(
                  "text",
                  {
                    key: 0,
                    class: "mbadge"
                  },
                  vue.toDisplayString(m.badge),
                  1
                  /* TEXT */
                )) : vue.createCommentVNode("v-if", true),
                vue.createElementVNode("text", { class: "ma" }, "›")
              ], 10, ["onClick"]);
            }),
            128
            /* KEYED_FRAGMENT */
          ))
        ]),
        vue.createElementVNode("view", { class: "mcard" }, [
          vue.createElementVNode("view", { class: "mbrow" }, [
            vue.createElementVNode("text", { class: "k" }, "版本"),
            vue.createElementVNode("text", { class: "v" }, "小程序端 v1.0.0")
          ]),
          vue.createElementVNode("view", { class: "mbrow" }, [
            vue.createElementVNode("text", { class: "k" }, "后端"),
            vue.createElementVNode(
              "text",
              { class: "v mono" },
              vue.toDisplayString($setup.apiModeText),
              1
              /* TEXT */
            )
          ])
        ]),
        $setup.userStore.loggedIn ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 0,
          class: "btn ghost block out",
          "hover-class": "btn-on",
          "hover-stay-time": 60,
          onClick: $setup.askLogout
        }, "退出登录")) : vue.createCommentVNode("v-if", true)
      ]),
      vue.createVNode(_component_mp_tab_bar, { current: 4 })
    ]);
  }
  const PagesMineIndex = /* @__PURE__ */ _export_sfc(_sfc_main$9, [["render", _sfc_render$8], ["__scopeId", "data-v-569e925a"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/mine/index.vue"]]);
  const _sfc_main$8 = {
    __name: "index",
    setup(__props, { expose: __expose }) {
      __expose();
      onUnload(() => resetLoading());
      const username = vue.ref("");
      const password = vue.ref("");
      const loading = vue.ref(false);
      const canSubmit = vue.computed(() => !!username.value.trim() && !!password.value);
      async function doSubmit() {
        if (loading.value)
          return;
        const name = username.value.trim();
        if (!name) {
          toast("请输入用户名");
          return;
        }
        if (!password.value) {
          toast("请输入密码");
          return;
        }
        loading.value = true;
        showLoading("登录中…");
        try {
          await doLogin({ username: name, password: password.value });
          toastOk("登录成功");
          goBack();
        } catch (e) {
          toast(e.message || "登录失败，请检查账号密码");
        } finally {
          loading.value = false;
          hideLoading();
        }
      }
      function goBack() {
        const pages = getCurrentPages();
        if (pages && pages.length > 1) {
          uni.navigateBack();
        } else {
          uni.reLaunch({ url: "/pages/index/index" });
        }
      }
      function skip() {
        uni.reLaunch({ url: "/pages/index/index" });
      }
      const __returned__ = { username, password, loading, canSubmit, doSubmit, goBack, skip, ref: vue.ref, computed: vue.computed, get onUnload() {
        return onUnload;
      }, get doLogin() {
        return doLogin;
      }, get toast() {
        return toast;
      }, get toastOk() {
        return toastOk;
      }, get showLoading() {
        return showLoading;
      }, get hideLoading() {
        return hideLoading;
      }, get resetLoading() {
        return resetLoading;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$7(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "登录",
        back: "",
        border: ""
      }),
      vue.createElementVNode("view", { class: "app-body" }, [
        vue.createElementVNode("view", { class: "brand" }, [
          vue.createElementVNode("view", { class: "orb" }, [
            vue.createElementVNode("text", { class: "big" }, "🧠")
          ]),
          vue.createElementVNode("text", { class: "bt" }, "AI 全感知 · 智能空间与设备综合调度平台"),
          vue.createElementVNode("text", { class: "bs" }, "登录后可查看预约、提交巡检、接收通知")
        ]),
        vue.createElementVNode("view", { class: "mcard" }, [
          vue.createElementVNode("view", { class: "field" }, [
            vue.createElementVNode("text", { class: "fl" }, "账号"),
            vue.withDirectives(vue.createElementVNode("input", {
              "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => $setup.username = $event),
              class: "fi",
              type: "text",
              placeholder: "请输入用户名",
              "placeholder-class": "ph",
              maxlength: 32,
              disabled: $setup.loading
            }, null, 8, ["disabled"]), [
              [vue.vModelText, $setup.username]
            ])
          ]),
          vue.createElementVNode("view", { class: "field" }, [
            vue.createElementVNode("text", { class: "fl" }, "密码"),
            vue.withDirectives(vue.createElementVNode("input", {
              "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => $setup.password = $event),
              class: "fi",
              type: "password",
              placeholder: "请输入密码",
              "placeholder-class": "ph",
              maxlength: 64,
              disabled: $setup.loading,
              onConfirm: $setup.doSubmit
            }, null, 40, ["disabled"]), [
              [vue.vModelText, $setup.password]
            ])
          ])
        ]),
        vue.createElementVNode(
          "view",
          {
            class: vue.normalizeClass(["btn ai block", { disabled: $setup.loading || !$setup.canSubmit }]),
            "hover-class": "btn-on",
            "hover-stay-time": 60,
            onClick: $setup.doSubmit
          },
          vue.toDisplayString($setup.loading ? "登录中…" : "登 录"),
          3
          /* TEXT, CLASS */
        ),
        vue.createElementVNode("view", {
          class: "btn ghost block later",
          "hover-class": "btn-on",
          onClick: $setup.skip
        }, "先逛逛"),
        vue.createElementVNode("text", { class: "tip" }, " 账号由管理员在后台创建。未启动后端时仍可浏览演示数据，但无法保存预约。 ")
      ])
    ]);
  }
  const PagesLoginIndex = /* @__PURE__ */ _export_sfc(_sfc_main$8, [["render", _sfc_render$7], ["__scopeId", "data-v-d08ef7d4"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/login/index.vue"]]);
  function asr(filePath) {
    return upload({ path: "/voice/asr", filePath, name: "file" });
  }
  function format(rawText) {
    return request({ path: "/voice/format", method: "POST", data: { rawText } });
  }
  function schedule(payload) {
    return request({
      path: "/agent/schedule",
      method: "POST",
      data: {
        text: payload.text || "",
        imageContext: payload.imageContext || {}
      }
    });
  }
  const agentStore = vue.reactive({
    /** 用户原始需求（口述文本或规整后的文本） */
    request: "",
    /** 拍照识场带过来的上下文，可为空 */
    imageContext: null,
    /** POST /agent/schedule 的完整返回 */
    payload: null,
    loading: false,
    error: "",
    /**
     * 方案生成失败时 Agent 对用户说的那句话（"请您补充使用时间…"）。
     *
     * 后端返回体里没有独立的消息字段，这句话只躺在 `trace` 最后一步的 `result` 里。
     * 存在这里是为了把它带到语音页当提示 —— 否则用户只看到「还没有生成方案」，
     * 不知道自己该补什么。
     */
    lastQuestion: ""
  });
  async function runSchedule(text, imageContext, force) {
    const sameRequest = text === agentStore.request;
    if (!force && sameRequest && agentStore.payload)
      return agentStore.payload;
    agentStore.request = text;
    if (imageContext !== void 0 && imageContext !== null) {
      agentStore.imageContext = imageContext;
    }
    agentStore.payload = null;
    agentStore.error = "";
    agentStore.lastQuestion = "";
    agentStore.loading = true;
    try {
      const data = await schedule({ text, imageContext: agentStore.imageContext || {} });
      agentStore.payload = data;
      return data;
    } catch (e) {
      agentStore.error = e.message || "AI 调度失败";
      throw e;
    } finally {
      agentStore.loading = false;
    }
  }
  function resetAgent() {
    agentStore.request = "";
    agentStore.imageContext = null;
    agentStore.payload = null;
    agentStore.error = "";
    agentStore.lastQuestion = "";
    agentStore.loading = false;
  }
  const _sfc_main$7 = {
    __name: "record",
    setup(__props, { expose: __expose }) {
      __expose();
      const recording = vue.ref(false);
      const recognizing = vue.ref(false);
      const seconds = vue.ref(0);
      const rawText = vue.ref("");
      const formattedText = vue.ref("");
      const keywords = vue.ref([]);
      const showInput = vue.ref(false);
      const manualText = vue.ref("");
      const editing = vue.ref(false);
      const draft = vue.ref("");
      const formatting = vue.ref(false);
      let fmtSeq = 0;
      const typing = vue.ref(false);
      const typed = vue.ref("");
      const autoFocus = vue.ref(false);
      const cursorPos = vue.ref(0);
      let typeTimer = null;
      let recorder = null;
      let timer = null;
      const timerText = vue.computed(() => {
        if (!recording.value && !seconds.value)
          return "";
        const m = Math.floor(seconds.value / 60);
        const s = seconds.value % 60;
        return `${m < 10 ? "0" + m : m}:${s < 10 ? "0" + s : s}`;
      });
      const hintText = vue.computed(() => {
        if (editing.value)
          return "改完点「保存并重新规整」";
        if (recording.value)
          return "正在聆听… 松开结束";
        if (recognizing.value)
          return "AI 正在识别语音…";
        if (typing.value)
          return "识别完成，稍后可直接修改";
        if (formatting.value)
          return "AI 正在规整为结构化约束…（文字已可用，可直接提交）";
        if (rawText.value)
          return "长按可以重新说一次";
        return "按住下方按钮，说出你的场地需求";
      });
      const agentText = vue.computed(() => formattedText.value || rawText.value);
      const chips = vue.computed(() => keywords.value);
      function classify(kw) {
        const s = String(kw);
        if (/预算|价格|费用|元|块钱|以内|以下/.test(s))
          return "ent b";
        if (/人|位|号人|规模/.test(s))
          return "ent n";
        if (/投影|音响|屏幕|显示屏|话筒|麦克|灯光|设备|白板|讲台/.test(s))
          return "ent d";
        if (/周|星期|上午|下午|晚上|中午|点|时段|今天|明天|后天|号/.test(s))
          return "ent t";
        return "ent t";
      }
      function buildSegments(text, kws) {
        const src = String(text || "");
        if (!src)
          return [];
        const hits = [];
        (kws || []).forEach((k) => {
          const kw = String(k || "");
          if (!kw)
            return;
          let from = 0;
          while (from <= src.length - kw.length) {
            const idx = src.indexOf(kw, from);
            if (idx < 0)
              break;
            hits.push({ start: idx, end: idx + kw.length, kw });
            from = idx + kw.length;
          }
        });
        if (!hits.length)
          return [{ text: src, cls: "" }];
        hits.sort((a, b) => a.start - b.start || b.end - b.start - (a.end - a.start));
        const picked = [];
        let lastEnd = -1;
        hits.forEach((h) => {
          if (h.start >= lastEnd) {
            picked.push(h);
            lastEnd = h.end;
          }
        });
        const segs = [];
        let cursor = 0;
        picked.forEach((h) => {
          if (h.start > cursor)
            segs.push({ text: src.slice(cursor, h.start), cls: "" });
          segs.push({ text: src.slice(h.start, h.end), cls: classify(h.kw) });
          cursor = h.end;
        });
        if (cursor < src.length)
          segs.push({ text: src.slice(cursor), cls: "" });
        return segs;
      }
      const segments = vue.computed(
        () => buildSegments(typing.value ? typed.value : rawText.value, keywords.value)
      );
      onLoad(() => {
        const pre = agentStore.request;
        if (pre) {
          rawText.value = pre;
          manualText.value = pre;
          enterEdit();
        } else {
          agentStore.imageContext = null;
        }
        recorder = uni.getRecorderManager();
        recorder.onStop((res) => {
          stopTimer();
          const path = res && res.tempFilePath;
          if (!path) {
            toast("没有录到声音，请重试");
            return;
          }
          if (seconds.value < 1) {
            toast("说话时间太短了");
            return;
          }
          recognize(path);
        });
        recorder.onError((err) => {
          recording.value = false;
          stopTimer();
          toast(err && err.errMsg || "录音失败");
        });
      });
      vue.onUnmounted(() => {
        stopTimer();
        stopTypewriter();
      });
      function startTimer() {
        seconds.value = 0;
        timer = setInterval(() => {
          seconds.value += 1;
          if (seconds.value >= RECORD_OPTIONS.duration / 1e3) {
            stopRecord();
          }
        }, 1e3);
      }
      function stopTimer() {
        if (timer) {
          clearInterval(timer);
          timer = null;
        }
      }
      function onPressStart() {
        if (recording.value || recognizing.value)
          return;
        if (editing.value) {
          toast("先保存或取消正在修改的文字");
          return;
        }
        recording.value = true;
        startTimer();
        try {
          recorder.start({
            duration: RECORD_OPTIONS.duration,
            sampleRate: RECORD_OPTIONS.sampleRate,
            numberOfChannels: RECORD_OPTIONS.numberOfChannels,
            encodeBitRate: RECORD_OPTIONS.encodeBitRate,
            format: RECORD_OPTIONS.format
          });
        } catch (e) {
          recording.value = false;
          stopTimer();
          toast("录音启动失败，请检查麦克风权限");
        }
      }
      function stopRecord() {
        if (!recording.value)
          return;
        recording.value = false;
        try {
          recorder.stop();
        } catch (e) {
          stopTimer();
        }
      }
      function onPressEnd() {
        stopRecord();
      }
      async function recognize(filePath) {
        stopTypewriter();
        editing.value = false;
        draft.value = "";
        fmtSeq += 1;
        formatting.value = false;
        recognizing.value = true;
        try {
          const asrRes = await asr(filePath);
          rawText.value = asrRes.text || "";
        } catch (e) {
          toast(e.message || "语音识别失败");
          return;
        } finally {
          recognizing.value = false;
        }
        if (!rawText.value) {
          toast("没听清，再说一次试试");
          return;
        }
        await typeOut(rawText.value);
        enterEdit();
        reformat(rawText.value);
      }
      function enterEdit() {
        draft.value = rawText.value;
        cursorPos.value = rawText.value.length;
        editing.value = true;
        autoFocus.value = true;
      }
      function onDraftBlur() {
        autoFocus.value = false;
      }
      function typeOut(src) {
        return new Promise((resolve) => {
          const text = String(src || "");
          typed.value = "";
          if (!text) {
            typing.value = false;
            resolve();
            return;
          }
          typing.value = true;
          const perTick = Math.max(1, Math.ceil(text.length / 40));
          typed.value = text.slice(0, perTick);
          typeTimer = setInterval(() => {
            typed.value = text.slice(0, typed.value.length + perTick);
            if (typed.value.length >= text.length) {
              stopTypewriter();
              resolve();
            }
          }, 30);
        });
      }
      function stopTypewriter() {
        if (typeTimer) {
          clearInterval(typeTimer);
          typeTimer = null;
        }
        typing.value = false;
      }
      async function useManual() {
        const text = manualText.value.trim();
        if (!text) {
          toast("请先输入需求");
          return;
        }
        cancelEdit();
        await reformat(text);
      }
      async function reformat(text) {
        const seq = ++fmtSeq;
        stopTypewriter();
        rawText.value = text;
        manualText.value = text;
        formattedText.value = "";
        keywords.value = [];
        formatting.value = true;
        try {
          const fmtRes = await format(text);
          if (seq !== fmtSeq)
            return;
          formattedText.value = fmtRes.formattedText || "";
          keywords.value = fmtRes.keywords || [];
        } catch (e) {
          if (seq !== fmtSeq)
            return;
          toast(e.message || "规整失败，将直接用原文提交");
        } finally {
          if (seq === fmtSeq)
            formatting.value = false;
        }
      }
      function startEdit() {
        if (recognizing.value || typing.value)
          return;
        enterEdit();
      }
      function cancelEdit() {
        stopTypewriter();
        editing.value = false;
        draft.value = "";
      }
      function applyEdit() {
        const text = draft.value.trim();
        if (!text) {
          toast("内容不能为空");
          return;
        }
        if (text === rawText.value) {
          cancelEdit();
          return;
        }
        cancelEdit();
        reformat(text);
      }
      function goAgent() {
        const text = agentText.value;
        if (!text) {
          toast("请先说出或输入你的需求");
          return;
        }
        agentStore.request = text;
        agentStore.lastQuestion = "";
        uni.navigateTo({ url: "/pages/agent/thinking" });
      }
      const __returned__ = { recording, recognizing, seconds, rawText, formattedText, keywords, showInput, manualText, editing, draft, formatting, get fmtSeq() {
        return fmtSeq;
      }, set fmtSeq(v) {
        fmtSeq = v;
      }, typing, typed, autoFocus, cursorPos, get typeTimer() {
        return typeTimer;
      }, set typeTimer(v) {
        typeTimer = v;
      }, get recorder() {
        return recorder;
      }, set recorder(v) {
        recorder = v;
      }, get timer() {
        return timer;
      }, set timer(v) {
        timer = v;
      }, timerText, hintText, agentText, chips, classify, buildSegments, segments, startTimer, stopTimer, onPressStart, stopRecord, onPressEnd, recognize, enterEdit, onDraftBlur, typeOut, stopTypewriter, useManual, reformat, startEdit, cancelEdit, applyEdit, goAgent, ref: vue.ref, computed: vue.computed, onUnmounted: vue.onUnmounted, get onLoad() {
        return onLoad;
      }, get asr() {
        return asr;
      }, get format() {
        return format;
      }, get agentStore() {
        return agentStore;
      }, get RECORD_OPTIONS() {
        return RECORD_OPTIONS;
      }, get toast() {
        return toast;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$6(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "语音预约",
        back: "",
        right: $setup.timerText
      }, null, 8, ["right"]),
      vue.createElementVNode("view", { class: "app-body has-cta" }, [
        $setup.agentStore.lastQuestion ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 0,
          class: "askcard"
        }, [
          vue.createElementVNode("text", { class: "askt" }, "🤖 AI 还需要你补充"),
          vue.createElementVNode(
            "text",
            { class: "askc" },
            vue.toDisplayString($setup.agentStore.lastQuestion),
            1
            /* TEXT */
          )
        ])) : vue.createCommentVNode("v-if", true),
        vue.createElementVNode(
          "view",
          {
            class: vue.normalizeClass(["rec", { on: $setup.recording }]),
            onTouchstart: $setup.onPressStart,
            onTouchend: $setup.onPressEnd,
            onTouchcancel: $setup.onPressEnd
          },
          [
            vue.createElementVNode("text", null, "🎙")
          ],
          34
          /* CLASS, NEED_HYDRATION */
        ),
        vue.createElementVNode(
          "view",
          {
            class: vue.normalizeClass(["wave", { off: !$setup.recording && !$setup.recognizing }])
          },
          [
            (vue.openBlock(), vue.createElementBlock(
              vue.Fragment,
              null,
              vue.renderList(12, (n) => {
                return vue.createElementVNode("view", {
                  key: n,
                  class: "bar"
                });
              }),
              64
              /* STABLE_FRAGMENT */
            ))
          ],
          2
          /* CLASS */
        ),
        vue.createElementVNode(
          "text",
          { class: "hint" },
          vue.toDisplayString($setup.hintText),
          1
          /* TEXT */
        ),
        $setup.segments.length ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 1,
          class: "asr"
        }, [
          !$setup.editing ? (vue.openBlock(), vue.createElementBlock(
            vue.Fragment,
            { key: 0 },
            [
              (vue.openBlock(true), vue.createElementBlock(
                vue.Fragment,
                null,
                vue.renderList($setup.segments, (s, i) => {
                  return vue.openBlock(), vue.createElementBlock(
                    "text",
                    {
                      key: i,
                      class: vue.normalizeClass(s.cls)
                    },
                    vue.toDisplayString(s.text),
                    3
                    /* TEXT, CLASS */
                  );
                }),
                128
                /* KEYED_FRAGMENT */
              )),
              $setup.recognizing || $setup.typing || $setup.formatting ? (vue.openBlock(), vue.createElementBlock("text", {
                key: 0,
                class: "caret"
              })) : vue.createCommentVNode("v-if", true)
            ],
            64
            /* STABLE_FRAGMENT */
          )) : vue.withDirectives((vue.openBlock(), vue.createElementBlock("textarea", {
            key: 1,
            "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => $setup.draft = $event),
            class: "earea",
            maxlength: 200,
            "auto-height": "",
            focus: $setup.autoFocus,
            cursor: $setup.cursorPos,
            "cursor-spacing": 24,
            onBlur: $setup.onDraftBlur
          }, null, 40, ["focus", "cursor"])), [
            [vue.vModelText, $setup.draft]
          ])
        ])) : vue.createCommentVNode("v-if", true),
        $setup.segments.length ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 2,
          class: "asrbar"
        }, [
          !$setup.editing ? (vue.openBlock(), vue.createElementBlock("text", {
            key: 0,
            class: "alink",
            onClick: $setup.startEdit
          }, "✏️ 继续修改")) : (vue.openBlock(), vue.createElementBlock(
            vue.Fragment,
            { key: 1 },
            [
              vue.createElementVNode("text", {
                class: "alink gray",
                onClick: $setup.cancelEdit
              }, "取消"),
              vue.createElementVNode("text", {
                class: "alink",
                onClick: $setup.applyEdit
              }, "保存并重新规整")
            ],
            64
            /* STABLE_FRAGMENT */
          ))
        ])) : vue.createCommentVNode("v-if", true),
        $setup.chips.length ? (vue.openBlock(), vue.createElementBlock(
          vue.Fragment,
          { key: 3 },
          [
            vue.createElementVNode("text", { class: "sect" }, "🤖 AI 已规整为结构化约束"),
            vue.createElementVNode("view", { class: "chips" }, [
              (vue.openBlock(true), vue.createElementBlock(
                vue.Fragment,
                null,
                vue.renderList($setup.chips, (c, i) => {
                  return vue.openBlock(), vue.createElementBlock(
                    "text",
                    {
                      key: i,
                      class: "chip"
                    },
                    vue.toDisplayString(c),
                    1
                    /* TEXT */
                  );
                }),
                128
                /* KEYED_FRAGMENT */
              ))
            ])
          ],
          64
          /* STABLE_FRAGMENT */
        )) : vue.createCommentVNode("v-if", true),
        vue.createElementVNode("view", { class: "manual" }, [
          vue.createElementVNode(
            "text",
            {
              class: "mlink",
              onClick: _cache[1] || (_cache[1] = ($event) => $setup.showInput = !$setup.showInput)
            },
            vue.toDisplayString($setup.showInput ? "收起手动输入" : "不方便说话？手动输入 ›"),
            1
            /* TEXT */
          ),
          $setup.showInput ? (vue.openBlock(), vue.createElementBlock(
            vue.Fragment,
            { key: 0 },
            [
              vue.withDirectives(vue.createElementVNode(
                "textarea",
                {
                  "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => $setup.manualText = $event),
                  class: "marea",
                  placeholder: "例：本周五下午要个能坐 40 人的展厅，带双投影和音响，预算 1000 以内，没大场地就拆两个小的",
                  maxlength: 200,
                  "auto-height": ""
                },
                null,
                512
                /* NEED_PATCH */
              ), [
                [vue.vModelText, $setup.manualText]
              ]),
              vue.createElementVNode("view", {
                class: "btn ghost",
                "hover-class": "btn-on",
                onClick: $setup.useManual
              }, "用这段文字")
            ],
            64
            /* STABLE_FRAGMENT */
          )) : vue.createCommentVNode("v-if", true)
        ])
      ]),
      vue.createElementVNode("view", { class: "app-cta" }, [
        vue.createElementVNode(
          "view",
          {
            class: vue.normalizeClass(["btn ai block", { disabled: !$setup.agentText }]),
            "hover-class": "btn-on",
            "hover-stay-time": 60,
            onClick: $setup.goAgent
          },
          vue.toDisplayString($setup.formatting ? "AI 规整中… 可直接提交" : "交给 AI 生成方案 →"),
          3
          /* TEXT, CLASS */
        )
      ])
    ]);
  }
  const PagesVoiceRecord = /* @__PURE__ */ _export_sfc(_sfc_main$7, [["render", _sfc_render$6], ["__scopeId", "data-v-106f66db"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/voice/record.vue"]]);
  const _sfc_main$6 = {
    __name: "thinking",
    setup(__props, { expose: __expose }) {
      __expose();
      const error = vue.ref("");
      const steps = vue.ref([]);
      const visibleCount = vue.ref(0);
      const elapsed = vue.ref(0);
      const payloadReady = vue.ref(false);
      let tickTimer = null;
      let revealTimer = null;
      const request2 = vue.computed(() => agentStore.request);
      const elapsedText = vue.computed(() => {
        if (!elapsed.value)
          return "";
        return `${(elapsed.value / 10).toFixed(1)}s`;
      });
      const ready = vue.computed(() => payloadReady.value && steps.value.length > 0);
      const visibleSteps = vue.computed(() => steps.value.slice(0, visibleCount.value));
      function normalizeTrace(trace) {
        return (trace || []).map((t, i) => ({
          step: t.step === void 0 || t.step === null ? i + 1 : t.step,
          title: t.result || `步骤 ${i + 1}`,
          time: (t.timestamp || "").slice(11),
          action: t.action || ""
        }));
      }
      function toneOf(s) {
        if (!s)
          return "";
        const title = String(s.title);
        if (/冲突|占用|不可用|降级|失败|超预算|不满足/.test(title))
          return "o";
        if (s.step === steps.value.length)
          return "g";
        return "";
      }
      onLoad(() => {
        tickTimer = setInterval(() => {
          elapsed.value += 1;
        }, 100);
        start();
      });
      vue.onUnmounted(() => {
        if (tickTimer)
          clearInterval(tickTimer);
        if (revealTimer)
          clearTimeout(revealTimer);
      });
      async function start() {
        error.value = "";
        payloadReady.value = false;
        steps.value = [];
        visibleCount.value = 0;
        try {
          const data = await runSchedule(agentStore.request, agentStore.imageContext);
          steps.value = normalizeTrace(data.trace);
          reveal();
        } catch (e) {
          error.value = e.message || "AI 调度失败";
          if (tickTimer)
            clearInterval(tickTimer);
        }
      }
      function reveal() {
        const total = steps.value.length;
        if (!total) {
          payloadReady.value = true;
          return;
        }
        const tick = () => {
          visibleCount.value += 1;
          if (visibleCount.value >= total) {
            payloadReady.value = true;
            if (tickTimer)
              clearInterval(tickTimer);
            return;
          }
          revealTimer = setTimeout(tick, 450);
        };
        tick();
      }
      function retry() {
        if (tickTimer)
          clearInterval(tickTimer);
        elapsed.value = 0;
        tickTimer = setInterval(() => {
          elapsed.value += 1;
        }, 100);
        start();
      }
      function goPlan() {
        if (!steps.value.length)
          return;
        uni.navigateTo({ url: "/pages/agent/plan" });
      }
      const __returned__ = { error, steps, visibleCount, elapsed, payloadReady, get tickTimer() {
        return tickTimer;
      }, set tickTimer(v) {
        tickTimer = v;
      }, get revealTimer() {
        return revealTimer;
      }, set revealTimer(v) {
        revealTimer = v;
      }, request: request2, elapsedText, ready, visibleSteps, normalizeTrace, toneOf, start, reveal, retry, goPlan, ref: vue.ref, computed: vue.computed, onUnmounted: vue.onUnmounted, get onLoad() {
        return onLoad;
      }, get agentStore() {
        return agentStore;
      }, get runSchedule() {
        return runSchedule;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$5(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "AI 正在思考",
        back: "",
        right: $setup.elapsedText
      }, null, 8, ["right"]),
      vue.createElementVNode("view", { class: "app-body has-cta" }, [
        $setup.error ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 0,
          class: "witem red"
        }, [
          vue.createElementVNode("text", { class: "wt" }, "调度失败"),
          vue.createElementVNode(
            "text",
            { class: "wp" },
            vue.toDisplayString($setup.error),
            1
            /* TEXT */
          ),
          vue.createElementVNode("view", {
            class: "btn ghost",
            "hover-class": "btn-on",
            onClick: $setup.retry
          }, "重新尝试")
        ])) : (vue.openBlock(), vue.createElementBlock(
          vue.Fragment,
          { key: 1 },
          [
            $setup.request ? (vue.openBlock(), vue.createElementBlock("view", {
              key: 0,
              class: "req"
            }, [
              vue.createElementVNode("text", { class: "rq" }, "你的需求"),
              vue.createElementVNode(
                "text",
                {
                  class: "rt",
                  "user-select": true
                },
                vue.toDisplayString($setup.request),
                1
                /* TEXT */
              )
            ])) : vue.createCommentVNode("v-if", true),
            (vue.openBlock(true), vue.createElementBlock(
              vue.Fragment,
              null,
              vue.renderList($setup.visibleSteps, (s) => {
                return vue.openBlock(), vue.createElementBlock("view", {
                  key: s.step,
                  class: "mbstep"
                }, [
                  vue.createElementVNode(
                    "view",
                    {
                      class: vue.normalizeClass(["tnum", $setup.toneOf(s)])
                    },
                    vue.toDisplayString(s.step),
                    3
                    /* TEXT, CLASS */
                  ),
                  vue.createElementVNode("view", { class: "txt" }, [
                    vue.createElementVNode("view", { class: "sline" }, [
                      vue.createElementVNode(
                        "text",
                        { class: "ss" },
                        vue.toDisplayString(s.title),
                        1
                        /* TEXT */
                      ),
                      !s.action ? (vue.openBlock(), vue.createElementBlock("text", {
                        key: 0,
                        class: "tag gray"
                      }, "推理")) : vue.createCommentVNode("v-if", true)
                    ]),
                    s.time ? (vue.openBlock(), vue.createElementBlock(
                      "text",
                      {
                        key: 0,
                        class: "stime"
                      },
                      vue.toDisplayString(s.time),
                      1
                      /* TEXT */
                    )) : vue.createCommentVNode("v-if", true)
                  ])
                ]);
              }),
              128
              /* KEYED_FRAGMENT */
            )),
            !$setup.steps.length ? (vue.openBlock(), vue.createElementBlock("view", {
              key: 1,
              class: "waiting"
            }, [
              vue.createElementVNode("view", { class: "live b" }),
              vue.createElementVNode("text", null, "正在解析需求、检索场地、校验冲突…")
            ])) : vue.createCommentVNode("v-if", true)
          ],
          64
          /* STABLE_FRAGMENT */
        ))
      ]),
      vue.createElementVNode("view", { class: "app-cta" }, [
        vue.createElementVNode(
          "view",
          {
            class: vue.normalizeClass(["btn ai block", { disabled: !$setup.ready }]),
            "hover-class": "btn-on",
            "hover-stay-time": 60,
            onClick: $setup.goPlan
          },
          "查看方案 →",
          2
          /* CLASS */
        )
      ])
    ]);
  }
  const PagesAgentThinking = /* @__PURE__ */ _export_sfc(_sfc_main$6, [["render", _sfc_render$5], ["__scopeId", "data-v-66e84719"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/agent/thinking.vue"]]);
  const _sfc_main$5 = {
    __name: "plan",
    setup(__props, { expose: __expose }) {
      __expose();
      onUnload(() => resetLoading());
      const submitting = vue.ref(false);
      const isMain = vue.ref(true);
      const payload = vue.computed(() => agentStore.payload);
      const mainPlan = vue.computed(() => payload.value ? payload.value.plan : null);
      const backupPlan = vue.computed(() => payload.value ? payload.value.backupPlan : null);
      const active = vue.computed(() => (isMain.value ? mainPlan.value : backupPlan.value) || null);
      const other = vue.computed(() => (isMain.value ? backupPlan.value : mainPlan.value) || null);
      const sideLabel = vue.computed(() => isMain.value ? "主方案" : "备选方案");
      const activeTitle = vue.computed(() => isMain.value ? "🤖 推荐方案" : "🤖 备选方案");
      function nameOf(p) {
        if (!p)
          return "";
        return first(p.spaceName, p.name, "未知场地");
      }
      function rangeOf(p) {
        if (!p)
          return "";
        return formatTimeRange(p.startTime, p.endTime);
      }
      const spaceLine = vue.computed(() => `场地：${nameOf(active.value)}`);
      const timeLine = vue.computed(() => rangeOf(active.value) || "时段待定");
      const deviceLine = vue.computed(() => {
        const ids = active.value ? active.value.deviceIds : null;
        if (!ids || !ids.length)
          return "";
        return `设备：${ids.length} 台（编号 ${ids.join("、")}）`;
      });
      const priceText = vue.computed(() => {
        const p = active.value;
        if (!p)
          return "";
        const raw = first(p.price, p.totalPrice, p.budget, p.amount);
        if (raw === void 0 || raw === null || raw === "")
          return "";
        return formatMoney(raw);
      });
      function diffOf(p) {
        if (!p || !p.reason)
          return "见决策依据";
        const s = String(p.reason);
        return s.length > 40 ? `${s.slice(0, 40)}…` : s;
      }
      const summary = vue.computed(() => {
        const p = active.value;
        if (!p)
          return "";
        const parts = [`${nameOf(p)}`];
        const range = rangeOf(p);
        if (range)
          parts.push(range);
        if (p.deviceIds && p.deviceIds.length)
          parts.push(`含 ${p.deviceIds.length} 台设备`);
        else
          parts.push("不含设备");
        return `${parts.join("，")}。`;
      });
      const tags = vue.computed(() => {
        const out = [];
        const combined = `${active.value && active.value.reason ? active.value.reason : ""}`;
        if (/降级/.test(combined))
          out.push({ tone: "orange", text: "设备已降级" });
        if (/拆分|两个|两间/.test(combined))
          out.push({ tone: "purple", text: "场地已拆分" });
        if (payload.value && payload.value.needConfirm)
          out.push({ tone: "blue", text: "待你确认" });
        if (backupPlan.value)
          out.push({ tone: "gray", text: "含备选方案" });
        return out;
      });
      function toggle() {
        if (!other.value)
          return;
        isMain.value = !isMain.value;
      }
      const agentReply = vue.computed(() => {
        const p = payload.value;
        if (!p || p.plan)
          return "";
        const trace = Array.isArray(p.trace) ? p.trace : [];
        for (let i = trace.length - 1; i >= 0; i--) {
          const t = trace[i];
          if (t && !t.action && t.result)
            return String(t.result);
        }
        const last = trace.length ? trace[trace.length - 1] : null;
        return last && last.result ? String(last.result) : "";
      });
      function goVoice() {
        agentStore.lastQuestion = agentReply.value || "";
        uni.navigateTo({ url: "/pages/voice/record" });
      }
      async function submit2() {
        if (submitting.value)
          return;
        const p = active.value;
        if (!p)
          return;
        if (!p.startTime || !p.endTime) {
          toast("方案缺少时段信息，无法创建预约");
          return;
        }
        submitting.value = true;
        const lockedId = isMain.value && payload.value ? payload.value.orderId : null;
        showLoading(lockedId ? "确认方案中…" : "创建预约中…");
        try {
          const order = lockedId ? await confirmOrder(lockedId) : await createOrder({
            spaceId: p.spaceId,
            deviceIds: p.deviceIds || [],
            startTime: p.startTime,
            endTime: p.endTime,
            agentRequest: agentStore.request,
            agentTrace: payload.value ? payload.value.trace : null
          });
          toastOk(lockedId ? "预约已确认" : "预约已创建");
          resetAgent();
          const id = first(order && order.orderId, order && order.id);
          if (id !== void 0) {
            uni.redirectTo({ url: `/pages/order/detail?orderId=${id}` });
          } else {
            uni.reLaunch({ url: TABS[1].path });
          }
        } catch (e) {
          toast(e.message || "创建预约失败");
        } finally {
          submitting.value = false;
          hideLoading();
        }
      }
      const __returned__ = { submitting, isMain, payload, mainPlan, backupPlan, active, other, sideLabel, activeTitle, nameOf, rangeOf, spaceLine, timeLine, deviceLine, priceText, diffOf, summary, tags, toggle, agentReply, goVoice, submit: submit2, ref: vue.ref, computed: vue.computed, get onUnload() {
        return onUnload;
      }, get agentStore() {
        return agentStore;
      }, get resetAgent() {
        return resetAgent;
      }, get confirmOrder() {
        return confirmOrder;
      }, get createOrder() {
        return createOrder;
      }, get formatTimeRange() {
        return formatTimeRange;
      }, get formatMoney() {
        return formatMoney;
      }, get first() {
        return first;
      }, get toast() {
        return toast;
      }, get toastOk() {
        return toastOk;
      }, get showLoading() {
        return showLoading;
      }, get hideLoading() {
        return hideLoading;
      }, get resetLoading() {
        return resetLoading;
      }, get TABS() {
        return TABS;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$4(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "方案确认",
        back: "",
        right: $setup.sideLabel
      }, null, 8, ["right"]),
      vue.createElementVNode("view", { class: "app-body has-cta" }, [
        !$setup.active ? (vue.openBlock(), vue.createElementBlock(
          vue.Fragment,
          { key: 0 },
          [
            vue.createElementVNode("view", { class: "mcard" }, [
              vue.createElementVNode("view", { class: "mtitle" }, "🤖 AI 还需要你补充一点信息"),
              vue.createElementVNode(
                "text",
                { class: "mtext" },
                vue.toDisplayString($setup.agentReply || "暂时没能生成方案。补充一下时间、人数或设备，我再算一次。"),
                1
                /* TEXT */
              )
            ]),
            vue.createElementVNode("view", { class: "mcard" }, [
              vue.createElementVNode("view", { class: "mtitle" }, "接下来怎么做"),
              vue.createElementVNode("text", { class: "mtext" }, " 回到语音页接着说就行——场地已经记住了，你只需要补上时间 （例如「明天下午两点到四点」），不用把场地再描述一遍。 ")
            ])
          ],
          64
          /* STABLE_FRAGMENT */
        )) : (vue.openBlock(), vue.createElementBlock(
          vue.Fragment,
          { key: 1 },
          [
            vue.createElementVNode("view", { class: "plan" }, [
              vue.createElementVNode(
                "text",
                { class: "tt" },
                vue.toDisplayString($setup.activeTitle),
                1
                /* TEXT */
              ),
              vue.createElementVNode(
                "text",
                { class: "dd" },
                vue.toDisplayString($setup.spaceLine),
                1
                /* TEXT */
              ),
              vue.createElementVNode(
                "text",
                { class: "dd" },
                vue.toDisplayString($setup.timeLine),
                1
                /* TEXT */
              ),
              $setup.deviceLine ? (vue.openBlock(), vue.createElementBlock(
                "text",
                {
                  key: 0,
                  class: "dd"
                },
                vue.toDisplayString($setup.deviceLine),
                1
                /* TEXT */
              )) : vue.createCommentVNode("v-if", true),
              $setup.priceText ? (vue.openBlock(), vue.createElementBlock(
                "text",
                {
                  key: 1,
                  class: "price"
                },
                vue.toDisplayString($setup.priceText),
                1
                /* TEXT */
              )) : vue.createCommentVNode("v-if", true)
            ]),
            $setup.active.reason ? (vue.openBlock(), vue.createElementBlock("view", {
              key: 0,
              class: "mcard"
            }, [
              vue.createElementVNode("view", { class: "mtitle" }, "🤖 AI 决策依据"),
              vue.createElementVNode(
                "text",
                { class: "mtext" },
                vue.toDisplayString($setup.active.reason),
                1
                /* TEXT */
              )
            ])) : vue.createCommentVNode("v-if", true),
            $setup.other ? (vue.openBlock(), vue.createElementBlock("view", {
              key: 1,
              class: "mcard"
            }, [
              vue.createElementVNode("view", { class: "mtitle" }, [
                vue.createElementVNode(
                  "text",
                  null,
                  vue.toDisplayString($setup.isMain ? "备选方案" : "主方案"),
                  1
                  /* TEXT */
                ),
                vue.createElementVNode("text", {
                  class: "more",
                  onClick: $setup.toggle
                }, "点击切换")
              ]),
              vue.createElementVNode("view", { class: "mbrow" }, [
                vue.createElementVNode("text", { class: "k" }, "场地"),
                vue.createElementVNode(
                  "text",
                  { class: "v" },
                  vue.toDisplayString($setup.nameOf($setup.other)),
                  1
                  /* TEXT */
                )
              ]),
              vue.createElementVNode("view", { class: "mbrow" }, [
                vue.createElementVNode("text", { class: "k" }, "时段"),
                vue.createElementVNode(
                  "text",
                  { class: "v" },
                  vue.toDisplayString($setup.rangeOf($setup.other) || "—"),
                  1
                  /* TEXT */
                )
              ]),
              vue.createElementVNode("view", { class: "mbrow" }, [
                vue.createElementVNode("text", { class: "k" }, "差异"),
                vue.createElementVNode(
                  "text",
                  { class: "v warn" },
                  vue.toDisplayString($setup.diffOf($setup.other)),
                  1
                  /* TEXT */
                )
              ])
            ])) : vue.createCommentVNode("v-if", true),
            vue.createElementVNode("view", { class: "mcard" }, [
              vue.createElementVNode("view", { class: "mtitle" }, "🤖 AI 预约摘要"),
              vue.createElementVNode(
                "text",
                { class: "mtext" },
                vue.toDisplayString($setup.summary),
                1
                /* TEXT */
              ),
              vue.createElementVNode("view", { class: "tags" }, [
                (vue.openBlock(true), vue.createElementBlock(
                  vue.Fragment,
                  null,
                  vue.renderList($setup.tags, (t, i) => {
                    return vue.openBlock(), vue.createElementBlock(
                      "text",
                      {
                        key: i,
                        class: vue.normalizeClass(["tag", t.tone])
                      },
                      vue.toDisplayString(t.text),
                      3
                      /* TEXT, CLASS */
                    );
                  }),
                  128
                  /* KEYED_FRAGMENT */
                ))
              ])
            ]),
            vue.createElementVNode("text", { class: "note" }, " 确认后将在同一事务内锁定场地与设备并生成预约单，冲突校验由后端再次执行。 ")
          ],
          64
          /* STABLE_FRAGMENT */
        ))
      ]),
      !$setup.active ? (vue.openBlock(), vue.createElementBlock("view", {
        key: 0,
        class: "app-cta"
      }, [
        vue.createElementVNode("view", {
          class: "btn ai block",
          "hover-class": "btn-on",
          "hover-stay-time": 60,
          onClick: $setup.goVoice
        }, " 补充时间 / 改需求 → ")
      ])) : vue.createCommentVNode("v-if", true),
      $setup.active ? (vue.openBlock(), vue.createElementBlock("view", {
        key: 1,
        class: "app-cta"
      }, [
        vue.createElementVNode("view", { class: "app-cta-row" }, [
          $setup.other ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 0,
            class: "btn ghost",
            "hover-class": "btn-on",
            "hover-stay-time": 60,
            onClick: $setup.toggle
          }, "换备选")) : vue.createCommentVNode("v-if", true),
          vue.createElementVNode(
            "view",
            {
              class: vue.normalizeClass(["btn ai grow", { disabled: $setup.submitting }]),
              "hover-class": "btn-on",
              "hover-stay-time": 60,
              onClick: $setup.submit
            },
            vue.toDisplayString($setup.submitting ? "创建中…" : "确认并创建预约"),
            3
            /* TEXT, CLASS */
          )
        ])
      ])) : vue.createCommentVNode("v-if", true)
    ]);
  }
  const PagesAgentPlan = /* @__PURE__ */ _export_sfc(_sfc_main$5, [["render", _sfc_render$4], ["__scopeId", "data-v-72a20bc0"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/agent/plan.vue"]]);
  function analyze(filePath) {
    return upload({ path: "/image/analyze", filePath, name: "file", silent: true });
  }
  const SLOT_DAYS = 14;
  const SLOT_MIN_MINUTES = 60;
  const SLOT_PER_DAY_MAX = 6;
  const _sfc_main$4 = {
    __name: "recognize",
    setup(__props, { expose: __expose }) {
      __expose();
      onUnload(() => resetLoading());
      const WEEKDAY_CN = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
      const photo = vue.ref("");
      const result = vue.ref(null);
      const analyzing = vue.ref(false);
      const spaceMeta = vue.ref(null);
      const slotsByDay = vue.ref({});
      const selectedDay = vue.ref("");
      const selectedSlot = vue.ref(null);
      const slotsLoading = vue.ref(false);
      const slotsNote = vue.ref("");
      const dayOptions = vue.computed(() => {
        const now = /* @__PURE__ */ new Date();
        const out = [];
        for (let i = 0; i < SLOT_DAYS; i++) {
          const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i);
          const key = ymd(day);
          out.push({
            key,
            label: dayLabel(i, day),
            sub: pad2(day.getMonth() + 1) + "-" + pad2(day.getDate()),
            hasSlot: (slotsByDay.value[key] || []).length > 0
          });
        }
        return out;
      });
      const currentSlots = vue.computed(() => slotsByDay.value[selectedDay.value] || []);
      const hasSelectableSlots = vue.computed(
        () => Object.keys(slotsByDay.value).some((k) => (slotsByDay.value[k] || []).length > 0)
      );
      const needsSlot = vue.computed(() => hasSelectableSlots.value && !selectedSlot.value);
      const candidates = vue.computed(() => {
        const c = result.value ? result.value.candidates : null;
        return Array.isArray(c) ? c : [];
      });
      const devices2 = vue.computed(() => {
        const d = result.value ? result.value.devices : null;
        return Array.isArray(d) ? d : [];
      });
      const requirements = vue.computed(() => {
        const r = result.value ? result.value.requirements : null;
        return Array.isArray(r) ? r : [];
      });
      const displayName2 = vue.computed(() => {
        const r = result.value;
        if (!r)
          return "";
        return first(r.spaceName, r.name, "未识别出场地名");
      });
      const typeText = vue.computed(() => {
        const t = result.value ? result.value.type : "";
        if (t === "space")
          return "实体场地";
        if (t === "sketch")
          return "手绘草图";
        return spaceTypeLabel(t);
      });
      const confidenceText = vue.computed(() => {
        const c = result.value ? result.value.confidence : null;
        if (c === void 0 || c === null || c === "")
          return "";
        const n = Number(c);
        if (isNaN(n))
          return "";
        const pct = n <= 1 ? Math.round(n * 100) : Math.round(n);
        return `置信度 ${pct}%`;
      });
      function confSuffix(c) {
        const n = Number(c);
        if (!c || isNaN(n))
          return "";
        return `（${n <= 1 ? Math.round(n * 100) : Math.round(n)}%）`;
      }
      function candidateName(c) {
        if (typeof c === "string")
          return c;
        return first(c.spaceName, c.name, "候选场地");
      }
      function candidateConf(c) {
        if (typeof c === "string")
          return "";
        const n = Number(c.confidence);
        if (!c.confidence || isNaN(n))
          return "";
        return `${n <= 1 ? Math.round(n * 100) : Math.round(n)}%`;
      }
      function pick2() {
        if (analyzing.value)
          return;
        const onPicked = (path, size) => {
          if (!validate(path, size))
            return;
          photo.value = path;
          result.value = null;
          run(path);
        };
        if (typeof uni.chooseMedia === "function") {
          uni.chooseMedia({
            count: 1,
            mediaType: ["image"],
            sourceType: ["camera", "album"],
            sizeType: ["compressed"],
            success: (res) => {
              const f = res.tempFiles && res.tempFiles[0];
              if (f)
                onPicked(f.tempFilePath, f.size);
            },
            fail: () => {
            }
          });
          return;
        }
        uni.chooseImage({
          count: 1,
          sizeType: ["compressed"],
          sourceType: ["camera", "album"],
          success: (res) => {
            const path = res.tempFilePaths && res.tempFilePaths[0];
            const file = res.tempFiles && res.tempFiles[0];
            if (path)
              onPicked(path, file ? file.size : 0);
          },
          fail: () => {
          }
        });
      }
      function validate(path, size) {
        if (size && size > IMAGE_LIMIT.MAX_MB * 1024 * 1024) {
          toast(`图片不能超过 ${IMAGE_LIMIT.MAX_MB}MB`);
          return false;
        }
        const m = String(path).match(/\.([a-zA-Z0-9]+)(?:\?|$)/);
        if (m && IMAGE_LIMIT.EXT.indexOf(m[1].toLowerCase()) < 0) {
          toast(`仅支持 ${IMAGE_LIMIT.EXT.join(" / ")}`);
          return false;
        }
        return true;
      }
      async function run(path) {
        analyzing.value = true;
        showLoading("AI 识别中…");
        try {
          result.value = await analyze(path);
          if (result.value && result.value.imageUrl) {
            result.value.imageUrl = absoluteUrl(result.value.imageUrl);
          }
          if (result.value && result.value.spaceId !== void 0 && result.value.spaceId !== null) {
            loadFreeSlots(result.value.spaceId);
          }
        } catch (e) {
          toast(e.message || "识别失败，请换一张照片试试");
          result.value = null;
        } finally {
          analyzing.value = false;
          hideLoading();
        }
      }
      function pickCandidate(c) {
        const name = candidateName(c);
        const sid = typeof c === "object" && c ? c.spaceId !== void 0 ? c.spaceId : c.id : void 0;
        result.value = { ...result.value, needConfirm: false, spaceName: name, spaceId: sid };
        toast(`已按「${name}」继续`);
        if (sid !== void 0 && sid !== null)
          loadFreeSlots(sid);
      }
      async function loadFreeSlots(spaceId) {
        slotsByDay.value = {};
        selectedDay.value = "";
        selectedSlot.value = null;
        spaceMeta.value = null;
        slotsNote.value = "";
        if (spaceId === void 0 || spaceId === null || spaceId === "")
          return;
        if (!userStore.loggedIn) {
          slotsNote.value = "登录后可查看这个场地的空闲时段";
          return;
        }
        slotsLoading.value = true;
        try {
          const res = await spaceBookings(spaceId, SLOT_DAYS);
          spaceMeta.value = res || null;
          slotsByDay.value = computeSlotsByDay(res);
          const firstKey = Object.keys(slotsByDay.value).find(
            (k) => (slotsByDay.value[k] || []).length > 0
          );
          if (firstKey) {
            selectedDay.value = firstKey;
          } else {
            slotsNote.value = `未来 ${SLOT_DAYS} 天没有 ${SLOT_MIN_MINUTES} 分钟以上的连续空档`;
          }
        } catch (e) {
          slotsNote.value = e && e.message || "空闲时段查询失败";
        } finally {
          slotsLoading.value = false;
        }
      }
      function computeSlotsByDay(res) {
        const out = {};
        const data = res || {};
        const bookings = Array.isArray(data.bookings) ? data.bookings : [];
        const openS = clockToMinutes(data.openStartTime);
        const openE = clockToMinutes(data.openEndTime);
        if (openS === null || openE === null || openE <= openS)
          return out;
        const busy = [];
        bookings.forEach((b) => {
          const s = parseDateTime(b.startTime);
          const e = parseDateTime(b.endTime);
          if (s && e && e > s)
            busy.push({ s, e });
        });
        busy.sort((a, b) => a.s.getTime() - b.s.getTime());
        const now = /* @__PURE__ */ new Date();
        for (let d = 0; d < SLOT_DAYS; d++) {
          const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + d);
          const dayKey = ymd(day);
          const dayStart = atMinutes(day, openS);
          const dayClose = atMinutes(day, openE);
          let cursor = dayStart;
          if (d === 0) {
            const r = new Date(now.getTime());
            r.setSeconds(0, 0);
            const rest = r.getMinutes() % 30;
            r.setMinutes(r.getMinutes() + (rest === 0 ? 30 : 30 - rest));
            if (r > cursor)
              cursor = r;
          }
          const list2 = [];
          if (cursor < dayClose) {
            for (const seg of busy) {
              if (seg.e <= dayStart || seg.s >= dayClose)
                continue;
              const s = seg.s < cursor ? cursor : seg.s;
              const e = seg.e > dayClose ? dayClose : seg.e;
              if (e <= cursor)
                continue;
              if (gapMinutes(cursor, s) >= SLOT_MIN_MINUTES) {
                list2.push(makeSlot(dayKey, cursor, s));
              }
              cursor = e;
              if (cursor >= dayClose)
                break;
              if (list2.length >= SLOT_PER_DAY_MAX)
                break;
            }
            if (list2.length < SLOT_PER_DAY_MAX && cursor < dayClose && gapMinutes(cursor, dayClose) >= SLOT_MIN_MINUTES) {
              list2.push(makeSlot(dayKey, cursor, dayClose));
            }
          }
          out[dayKey] = list2;
        }
        return out;
      }
      function clockToMinutes(t) {
        const m = String(t || "").match(/^(\d{1,2}):(\d{2})/);
        if (!m)
          return null;
        return Number(m[1]) * 60 + Number(m[2]);
      }
      function atMinutes(day, minutes) {
        const d = new Date(day.getFullYear(), day.getMonth(), day.getDate());
        d.setMinutes(minutes);
        return d;
      }
      function gapMinutes(a, b) {
        return Math.round((b.getTime() - a.getTime()) / 6e4);
      }
      function pad2(n) {
        return n < 10 ? "0" + n : String(n);
      }
      function hm(d) {
        return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
      }
      function ymd(d) {
        return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
      }
      function dayLabel(offset, day) {
        if (offset === 0)
          return "今天";
        if (offset === 1)
          return "明天";
        if (offset === 2)
          return "后天";
        return WEEKDAY_CN[day.getDay()];
      }
      function makeSlot(dayKey, start, end) {
        return {
          key: dayKey + " " + hm(start),
          dayKey,
          range: hm(start) + "-" + hm(end),
          // 给 Agent 的是**绝对时间**：相对时间（"明天"）靠模型自己换算不稳定，
          // 而这里我们已经精确知道是哪一天了，没必要让它再猜一次
          absolute: dayKey + " " + hm(start) + "-" + hm(end)
        };
      }
      function selectDay(d) {
        if (!d.hasSlot || selectedDay.value === d.key)
          return;
        selectedDay.value = d.key;
        selectedSlot.value = null;
      }
      function selectSlot(s) {
        selectedSlot.value = selectedSlot.value && selectedSlot.value.key === s.key ? null : s;
      }
      function pushImageContext() {
        const r = result.value;
        const meta = spaceMeta.value || {};
        const sid = r && r.spaceId !== void 0 && r.spaceId !== null ? r.spaceId : meta.spaceId;
        if (sid === void 0 || sid === null) {
          agentStore.imageContext = null;
          return;
        }
        agentStore.imageContext = {
          source: "image_analyze",
          spaceId: sid,
          spaceName: r && r.spaceName || meta.spaceName || "",
          spaceType: meta.spaceType,
          location: meta.location || "",
          capacity: meta.capacity,
          confidence: r ? r.confidence : void 0
        };
      }
      function goVoice() {
        if (!result.value)
          return;
        if (needsSlot.value) {
          toast("请先选一个日期和时间段");
          return;
        }
        const name = displayName2.value;
        const cap = spaceMeta.value && spaceMeta.value.capacity;
        const parts = [`我要预约${name}`];
        if (cap)
          parts.push(`${cap}人`);
        if (selectedSlot.value)
          parts.push(selectedSlot.value.absolute);
        agentStore.request = parts.join("，");
        pushImageContext();
        uni.navigateTo({ url: "/pages/voice/record" });
      }
      const __returned__ = { SLOT_DAYS, SLOT_MIN_MINUTES, SLOT_PER_DAY_MAX, WEEKDAY_CN, photo, result, analyzing, spaceMeta, slotsByDay, selectedDay, selectedSlot, slotsLoading, slotsNote, dayOptions, currentSlots, hasSelectableSlots, needsSlot, candidates, devices: devices2, requirements, displayName: displayName2, typeText, confidenceText, confSuffix, candidateName, candidateConf, pick: pick2, validate, run, pickCandidate, loadFreeSlots, computeSlotsByDay, clockToMinutes, atMinutes, gapMinutes, pad2, hm, ymd, dayLabel, makeSlot, selectDay, selectSlot, pushImageContext, goVoice, ref: vue.ref, computed: vue.computed, get onUnload() {
        return onUnload;
      }, get analyze() {
        return analyze;
      }, get absoluteUrl() {
        return absoluteUrl;
      }, get spaceBookings() {
        return spaceBookings;
      }, get spaceTypeLabel() {
        return spaceTypeLabel;
      }, get IMAGE_LIMIT() {
        return IMAGE_LIMIT;
      }, get first() {
        return first;
      }, get toast() {
        return toast;
      }, get showLoading() {
        return showLoading;
      }, get hideLoading() {
        return hideLoading;
      }, get resetLoading() {
        return resetLoading;
      }, get agentStore() {
        return agentStore;
      }, get userStore() {
        return userStore;
      }, get parseDateTime() {
        return parseDateTime;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$3(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "拍照识场",
        back: ""
      }),
      vue.createElementVNode("view", { class: "app-body has-cta" }, [
        vue.createElementVNode("view", {
          class: "imgbox",
          onClick: $setup.pick
        }, [
          $setup.photo ? (vue.openBlock(), vue.createElementBlock("image", {
            key: 0,
            class: "photo",
            src: $setup.photo,
            mode: "aspectFill"
          }, null, 8, ["src"])) : (vue.openBlock(), vue.createElementBlock("view", {
            key: 1,
            class: "cam"
          }, [
            vue.createElementVNode("text", { class: "big" }, "📷"),
            vue.createElementVNode("text", null, "拍下门牌或场地，AI 识别空间与可用设备")
          ])),
          $setup.photo ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 2,
            class: "bbox on-photo"
          }, [
            vue.createElementVNode("view", { class: "cn" }),
            vue.createElementVNode("view", { class: "cn" }),
            vue.createElementVNode("view", { class: "cn" }),
            vue.createElementVNode("view", { class: "cn" })
          ])) : vue.createCommentVNode("v-if", true),
          $setup.analyzing ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 3,
            class: "scanline"
          })) : vue.createCommentVNode("v-if", true)
        ]),
        $setup.result ? (vue.openBlock(), vue.createElementBlock("view", { key: 0 }, [
          $setup.result.needConfirm ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 0,
            class: "witem blue"
          }, [
            vue.createElementVNode("text", { class: "wt" }, "需要你确认一下"),
            vue.createElementVNode(
              "text",
              { class: "wp" },
              vue.toDisplayString($setup.result.question || "这张照片不太确定，请选择或补充信息。"),
              1
              /* TEXT */
            ),
            $setup.candidates.length ? (vue.openBlock(), vue.createElementBlock("view", {
              key: 0,
              class: "cands"
            }, [
              (vue.openBlock(true), vue.createElementBlock(
                vue.Fragment,
                null,
                vue.renderList($setup.candidates, (c, i) => {
                  return vue.openBlock(), vue.createElementBlock("view", {
                    key: i,
                    class: "cand",
                    "hover-class": "btn-on",
                    "hover-stay-time": 60,
                    onClick: ($event) => $setup.pickCandidate(c)
                  }, [
                    vue.createElementVNode(
                      "text",
                      { class: "cn-name" },
                      vue.toDisplayString($setup.candidateName(c)),
                      1
                      /* TEXT */
                    ),
                    $setup.candidateConf(c) ? (vue.openBlock(), vue.createElementBlock(
                      "text",
                      {
                        key: 0,
                        class: "cn-conf"
                      },
                      vue.toDisplayString($setup.candidateConf(c)),
                      1
                      /* TEXT */
                    )) : vue.createCommentVNode("v-if", true)
                  ], 8, ["onClick"]);
                }),
                128
                /* KEYED_FRAGMENT */
              ))
            ])) : vue.createCommentVNode("v-if", true)
          ])) : vue.createCommentVNode("v-if", true),
          vue.createElementVNode("view", { class: "mcard" }, [
            vue.createElementVNode("view", { class: "mtitle" }, [
              vue.createElementVNode("text", null, "🤖 AI 识别结果"),
              $setup.confidenceText ? (vue.openBlock(), vue.createElementBlock(
                "text",
                {
                  key: 0,
                  class: "more"
                },
                vue.toDisplayString($setup.confidenceText),
                1
                /* TEXT */
              )) : vue.createCommentVNode("v-if", true)
            ]),
            vue.createElementVNode("view", { class: "mbrow" }, [
              vue.createElementVNode("text", { class: "k" }, "场地"),
              vue.createElementVNode(
                "text",
                { class: "v" },
                vue.toDisplayString($setup.displayName),
                1
                /* TEXT */
              )
            ]),
            $setup.result.type ? (vue.openBlock(), vue.createElementBlock("view", {
              key: 0,
              class: "mbrow"
            }, [
              vue.createElementVNode("text", { class: "k" }, "类型"),
              vue.createElementVNode(
                "text",
                { class: "v" },
                vue.toDisplayString($setup.typeText),
                1
                /* TEXT */
              )
            ])) : vue.createCommentVNode("v-if", true),
            $setup.result.capacity ? (vue.openBlock(), vue.createElementBlock("view", {
              key: 1,
              class: "mbrow"
            }, [
              vue.createElementVNode("text", { class: "k" }, "容量"),
              vue.createElementVNode(
                "text",
                { class: "v" },
                vue.toDisplayString($setup.result.capacity) + " 人",
                1
                /* TEXT */
              )
            ])) : vue.createCommentVNode("v-if", true),
            $setup.result.layout ? (vue.openBlock(), vue.createElementBlock("view", {
              key: 2,
              class: "mbrow"
            }, [
              vue.createElementVNode("text", { class: "k" }, "布局"),
              vue.createElementVNode(
                "text",
                { class: "v" },
                vue.toDisplayString($setup.result.layout),
                1
                /* TEXT */
              )
            ])) : vue.createCommentVNode("v-if", true)
          ]),
          $setup.result.spaceId || $setup.slotsLoading || $setup.slotsNote ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 1,
            class: "mcard"
          }, [
            vue.createElementVNode("view", { class: "mtitle" }, [
              vue.createElementVNode("text", null, "选择使用时段"),
              $setup.slotsLoading ? (vue.openBlock(), vue.createElementBlock("text", {
                key: 0,
                class: "more"
              }, "查询中…")) : vue.createCommentVNode("v-if", true)
            ]),
            $setup.slotsLoading ? (vue.openBlock(), vue.createElementBlock("text", {
              key: 0,
              class: "mtext"
            }, " 正在查这个场地未来 " + vue.toDisplayString($setup.SLOT_DAYS) + " 天的占用… ")) : $setup.slotsNote ? (vue.openBlock(), vue.createElementBlock(
              "text",
              {
                key: 1,
                class: "mtext"
              },
              vue.toDisplayString($setup.slotsNote),
              1
              /* TEXT */
            )) : (vue.openBlock(), vue.createElementBlock(
              vue.Fragment,
              { key: 2 },
              [
                vue.createElementVNode("text", { class: "stepk" }, "1 · 选日期（未来两周）"),
                vue.createElementVNode("scroll-view", {
                  "scroll-x": "",
                  class: "dayscroll",
                  "show-scrollbar": false
                }, [
                  vue.createElementVNode("view", { class: "dayrow" }, [
                    (vue.openBlock(true), vue.createElementBlock(
                      vue.Fragment,
                      null,
                      vue.renderList($setup.dayOptions, (d) => {
                        return vue.openBlock(), vue.createElementBlock("view", {
                          key: d.key,
                          class: vue.normalizeClass(["day", { on: $setup.selectedDay === d.key, off: !d.hasSlot }]),
                          "hover-class": "btn-on",
                          "hover-stay-time": 60,
                          onClick: ($event) => $setup.selectDay(d)
                        }, [
                          vue.createElementVNode(
                            "text",
                            { class: "dl" },
                            vue.toDisplayString(d.label),
                            1
                            /* TEXT */
                          ),
                          vue.createElementVNode(
                            "text",
                            { class: "ds" },
                            vue.toDisplayString(d.sub),
                            1
                            /* TEXT */
                          )
                        ], 10, ["onClick"]);
                      }),
                      128
                      /* KEYED_FRAGMENT */
                    ))
                  ])
                ]),
                vue.createElementVNode(
                  "text",
                  { class: "stepk" },
                  "2 · 选时间段" + vue.toDisplayString($setup.selectedSlot ? "" : "（必选）"),
                  1
                  /* TEXT */
                ),
                !$setup.selectedDay ? (vue.openBlock(), vue.createElementBlock("text", {
                  key: 0,
                  class: "mtext"
                }, "先选一个日期")) : !$setup.currentSlots.length ? (vue.openBlock(), vue.createElementBlock("text", {
                  key: 1,
                  class: "mtext"
                }, " 这天没有可用的时段，换一天试试 ")) : (vue.openBlock(), vue.createElementBlock("view", {
                  key: 2,
                  class: "slotgrid"
                }, [
                  (vue.openBlock(true), vue.createElementBlock(
                    vue.Fragment,
                    null,
                    vue.renderList($setup.currentSlots, (s) => {
                      return vue.openBlock(), vue.createElementBlock("view", {
                        key: s.key,
                        class: vue.normalizeClass(["slotbtn", { on: $setup.selectedSlot && $setup.selectedSlot.key === s.key }]),
                        "hover-class": "btn-on",
                        "hover-stay-time": 60,
                        onClick: ($event) => $setup.selectSlot(s)
                      }, vue.toDisplayString(s.range), 11, ["onClick"]);
                    }),
                    128
                    /* KEYED_FRAGMENT */
                  ))
                ])),
                $setup.selectedSlot ? (vue.openBlock(), vue.createElementBlock(
                  "text",
                  {
                    key: 3,
                    class: "slotnote on"
                  },
                  " 已选 " + vue.toDisplayString($setup.selectedSlot.absolute) + " —— 点下面的按钮带着它去预约，跳过去还能改。 ",
                  1
                  /* TEXT */
                )) : (vue.openBlock(), vue.createElementBlock("text", {
                  key: 4,
                  class: "slotnote"
                }, " 先选日期，再点一个时间段；选好之后才能带着它去预约。 "))
              ],
              64
              /* STABLE_FRAGMENT */
            ))
          ])) : vue.createCommentVNode("v-if", true),
          $setup.devices.length ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 2,
            class: "mcard"
          }, [
            vue.createElementVNode("view", { class: "mtitle" }, "识别到的设备"),
            (vue.openBlock(true), vue.createElementBlock(
              vue.Fragment,
              null,
              vue.renderList($setup.devices, (d, i) => {
                return vue.openBlock(), vue.createElementBlock("view", {
                  key: i,
                  class: "mbrow"
                }, [
                  vue.createElementVNode(
                    "text",
                    { class: "k" },
                    vue.toDisplayString(d.deviceType || "设备"),
                    1
                    /* TEXT */
                  ),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString(d.count || 1) + " 台" + vue.toDisplayString($setup.confSuffix(d.confidence)),
                    1
                    /* TEXT */
                  )
                ]);
              }),
              128
              /* KEYED_FRAGMENT */
            ))
          ])) : vue.createCommentVNode("v-if", true),
          $setup.requirements.length ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 3,
            class: "mcard"
          }, [
            vue.createElementVNode("view", { class: "mtitle" }, "识别到的需求"),
            vue.createElementVNode("view", { class: "chips" }, [
              (vue.openBlock(true), vue.createElementBlock(
                vue.Fragment,
                null,
                vue.renderList($setup.requirements, (r, i) => {
                  return vue.openBlock(), vue.createElementBlock(
                    "text",
                    {
                      key: i,
                      class: "chip"
                    },
                    vue.toDisplayString(r),
                    1
                    /* TEXT */
                  );
                }),
                128
                /* KEYED_FRAGMENT */
              ))
            ])
          ])) : vue.createCommentVNode("v-if", true)
        ])) : vue.createCommentVNode("v-if", true),
        !$setup.photo ? (vue.openBlock(), vue.createElementBlock(
          "text",
          {
            key: 1,
            class: "note"
          },
          " 支持 " + vue.toDisplayString($setup.IMAGE_LIMIT.EXT.join(" / ")) + "，单张不超过 " + vue.toDisplayString($setup.IMAGE_LIMIT.MAX_MB) + "MB。 ",
          1
          /* TEXT */
        )) : vue.createCommentVNode("v-if", true)
      ]),
      vue.createElementVNode("view", { class: "app-cta" }, [
        !$setup.result ? (vue.openBlock(), vue.createElementBlock(
          "view",
          {
            key: 0,
            class: vue.normalizeClass(["btn ai block", { disabled: $setup.analyzing }]),
            "hover-class": "btn-on",
            "hover-stay-time": 60,
            onClick: $setup.pick
          },
          vue.toDisplayString($setup.analyzing ? "AI 识别中…" : "拍一张试试"),
          3
          /* TEXT, CLASS */
        )) : (vue.openBlock(), vue.createElementBlock("view", {
          key: 1,
          class: "app-cta-row"
        }, [
          vue.createElementVNode("view", {
            class: "btn ghost",
            "hover-class": "btn-on",
            onClick: $setup.pick
          }, "重拍"),
          vue.createElementVNode(
            "view",
            {
              class: vue.normalizeClass(["btn ai grow", { disabled: $setup.needsSlot }]),
              "hover-class": "btn-on",
              "hover-stay-time": 60,
              onClick: $setup.goVoice
            },
            vue.toDisplayString($setup.needsSlot ? "请先选时间段" : "带着它去预约 →"),
            3
            /* TEXT, CLASS */
          )
        ]))
      ])
    ]);
  }
  const PagesSpaceRecognize = /* @__PURE__ */ _export_sfc(_sfc_main$4, [["render", _sfc_render$3], ["__scopeId", "data-v-910b72f6"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/space/recognize.vue"]]);
  const _sfc_main$3 = {
    __name: "list",
    setup(__props, { expose: __expose }) {
      __expose();
      const SEGMENTS = [
        { key: "all", label: "全部" },
        { key: 1, label: "会议室" },
        { key: 2, label: "展厅" },
        { key: 3, label: "多功能厅" },
        { key: 4, label: "户外场地" }
      ];
      const DAY_OPTS = [7, 30];
      const list2 = vue.ref([]);
      const loading = vue.ref(true);
      const error = vue.ref("");
      const seg = vue.ref("all");
      const openId = vue.ref(null);
      const days = vue.ref(30);
      const cache = vue.ref({});
      const shown = vue.computed(() => {
        if (seg.value === "all")
          return list2.value;
        return list2.value.filter((s) => Number(s.spaceType) === seg.value);
      });
      const box = vue.computed(() => {
        const id = openId.value;
        if (id === null)
          return { loading: false, error: "", list: [] };
        return cache.value[id] || { loading: false, error: "", list: [] };
      });
      function nameOf(s) {
        return s.spaceName || "场地 #" + s.spaceId;
      }
      function openText(s) {
        const a = hhmm(s.openStartTime);
        const b = hhmm(s.openEndTime);
        return a + " ~ " + b;
      }
      function hhmm(t) {
        const v = String(t || "");
        return v ? v.slice(0, 5) : "不限";
      }
      function bookingText(b) {
        const s = parseDateTime(b.startTime);
        const e = parseDateTime(b.endTime);
        if (!s || !e)
          return String(b.startTime || "—");
        if (s.toDateString() === e.toDateString()) {
          return formatMonthDay(s) + " " + formatWeekday(s) + " " + formatTime(s) + " - " + formatTime(e);
        }
        return formatMonthDay(s) + " " + formatTime(s) + " - " + formatMonthDay(e) + " " + formatTime(e);
      }
      function deviceText(b) {
        const d = deviceLabel(b.deviceIds);
        return d && d !== "无" ? " · " + d : "";
      }
      onLoad(() => {
        ensureNameMaps();
        load();
      });
      async function load() {
        loading.value = true;
        try {
          const res = await spaces();
          list2.value = res.list || [];
          error.value = "";
        } catch (e) {
          list2.value = [];
          error.value = e && e.message || "场地列表加载失败";
        } finally {
          loading.value = false;
        }
      }
      function toggle(s) {
        const id = s.spaceId;
        if (openId.value === id) {
          openId.value = null;
          return;
        }
        openId.value = id;
        loadBookings(id);
      }
      async function loadBookings(id) {
        if (!userStore.loggedIn) {
          setBox(id, { loading: false, error: "登录后可查看占用时段", list: [] });
          return;
        }
        setBox(id, { loading: true, error: "", list: [] });
        try {
          const res = await spaceBookings(id, days.value);
          setBox(id, { loading: false, error: "", list: res && res.bookings || [] });
        } catch (e) {
          setBox(id, {
            loading: false,
            error: e && e.message || "占用时段查询失败",
            list: []
          });
        }
      }
      function setBox(id, val) {
        cache.value = Object.assign({}, cache.value, { [id]: val });
      }
      function setDays(d) {
        if (days.value === d)
          return;
        days.value = d;
        cache.value = {};
        if (openId.value !== null)
          loadBookings(openId.value);
      }
      const __returned__ = { SEGMENTS, DAY_OPTS, list: list2, loading, error, seg, openId, days, cache, shown, box, nameOf, openText, hhmm, bookingText, deviceText, load, toggle, loadBookings, setBox, setDays, ref: vue.ref, computed: vue.computed, get onLoad() {
        return onLoad;
      }, get fetchSpaces() {
        return spaces;
      }, get spaceBookings() {
        return spaceBookings;
      }, get ensureNameMaps() {
        return ensureNameMaps;
      }, get deviceLabel() {
        return deviceLabel;
      }, get statusLabel() {
        return statusLabel;
      }, get statusTag() {
        return statusTag;
      }, get spaceTypeLabel() {
        return spaceTypeLabel;
      }, get parseDateTime() {
        return parseDateTime;
      }, get formatTime() {
        return formatTime;
      }, get formatMonthDay() {
        return formatMonthDay;
      }, get formatWeekday() {
        return formatWeekday;
      }, get userStore() {
        return userStore;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$2(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    const _component_mp_empty = resolveEasycom(vue.resolveDynamicComponent("mp-empty"), __easycom_1);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "场地一览",
        back: ""
      }),
      vue.createElementVNode("view", { class: "app-body" }, [
        vue.createElementVNode("view", { class: "seg" }, [
          (vue.openBlock(), vue.createElementBlock(
            vue.Fragment,
            null,
            vue.renderList($setup.SEGMENTS, (s) => {
              return vue.createElementVNode("text", {
                key: s.key,
                class: vue.normalizeClass(["sg", { on: $setup.seg === s.key }]),
                onClick: ($event) => $setup.seg = s.key
              }, vue.toDisplayString(s.label), 11, ["onClick"]);
            }),
            64
            /* STABLE_FRAGMENT */
          ))
        ]),
        $setup.loading ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 0,
          class: "mcard"
        }, [
          vue.createElementVNode("text", { class: "mtext" }, "加载中…")
        ])) : $setup.error ? (vue.openBlock(), vue.createBlock(_component_mp_empty, {
          key: 1,
          icon: "⚠️",
          text: $setup.error,
          "action-text": "重试",
          onAction: $setup.load
        }, null, 8, ["text"])) : !$setup.shown.length ? (vue.openBlock(), vue.createBlock(_component_mp_empty, {
          key: 2,
          icon: "🏢",
          text: "没有符合条件的场地"
        })) : (vue.openBlock(), vue.createElementBlock(
          vue.Fragment,
          { key: 3 },
          [
            (vue.openBlock(true), vue.createElementBlock(
              vue.Fragment,
              null,
              vue.renderList($setup.shown, (s) => {
                return vue.openBlock(), vue.createElementBlock("view", {
                  key: s.spaceId,
                  class: "mcard sp"
                }, [
                  vue.createElementVNode("view", {
                    class: "sphead",
                    "hover-class": "btn-on",
                    "hover-stay-time": 60,
                    onClick: ($event) => $setup.toggle(s)
                  }, [
                    vue.createElementVNode("view", { class: "spmain" }, [
                      vue.createElementVNode("view", { class: "sptop" }, [
                        vue.createElementVNode(
                          "text",
                          { class: "spname" },
                          vue.toDisplayString($setup.nameOf(s)),
                          1
                          /* TEXT */
                        ),
                        vue.createElementVNode(
                          "text",
                          { class: "tag blue" },
                          vue.toDisplayString($setup.spaceTypeLabel(s.spaceType)),
                          1
                          /* TEXT */
                        ),
                        vue.createElementVNode(
                          "text",
                          {
                            class: vue.normalizeClass(["tag", $setup.statusTag("space", 0, s.occupancyText)])
                          },
                          vue.toDisplayString(s.occupancyText || "空闲"),
                          3
                          /* TEXT, CLASS */
                        )
                      ]),
                      vue.createElementVNode(
                        "text",
                        { class: "spmeta" },
                        "📍 " + vue.toDisplayString(s.location || "位置未登记"),
                        1
                        /* TEXT */
                      ),
                      vue.createElementVNode(
                        "text",
                        { class: "spmeta" },
                        "👥 可容纳 " + vue.toDisplayString(s.capacity) + " 人 · 🕘 " + vue.toDisplayString($setup.openText(s)),
                        1
                        /* TEXT */
                      )
                    ]),
                    vue.createElementVNode(
                      "text",
                      { class: "chev" },
                      vue.toDisplayString($setup.openId === s.spaceId ? "▾" : "›"),
                      1
                      /* TEXT */
                    )
                  ], 8, ["onClick"]),
                  $setup.openId === s.spaceId ? (vue.openBlock(), vue.createElementBlock("view", {
                    key: 0,
                    class: "bk"
                  }, [
                    vue.createElementVNode("view", { class: "bkhead" }, [
                      vue.createElementVNode("text", { class: "bkh" }, "已占用时段"),
                      vue.createElementVNode("view", { class: "bkd" }, [
                        (vue.openBlock(), vue.createElementBlock(
                          vue.Fragment,
                          null,
                          vue.renderList($setup.DAY_OPTS, (d) => {
                            return vue.createElementVNode("text", {
                              key: d,
                              class: vue.normalizeClass(["bd", { on: $setup.days === d }]),
                              onClick: vue.withModifiers(($event) => $setup.setDays(d), ["stop"])
                            }, vue.toDisplayString(d) + "天", 11, ["onClick"]);
                          }),
                          64
                          /* STABLE_FRAGMENT */
                        ))
                      ])
                    ]),
                    $setup.box.loading ? (vue.openBlock(), vue.createElementBlock("text", {
                      key: 0,
                      class: "bkmsg"
                    }, "查询中…")) : $setup.box.error ? (vue.openBlock(), vue.createElementBlock(
                      "text",
                      {
                        key: 1,
                        class: "bkmsg err"
                      },
                      vue.toDisplayString($setup.box.error),
                      1
                      /* TEXT */
                    )) : !$setup.box.list.length ? (vue.openBlock(), vue.createElementBlock(
                      "text",
                      {
                        key: 2,
                        class: "bkmsg ok"
                      },
                      " ✅ 未来 " + vue.toDisplayString($setup.days) + " 天没有占用，随时可约 ",
                      1
                      /* TEXT */
                    )) : (vue.openBlock(), vue.createElementBlock(
                      vue.Fragment,
                      { key: 3 },
                      [
                        (vue.openBlock(true), vue.createElementBlock(
                          vue.Fragment,
                          null,
                          vue.renderList($setup.box.list, (b) => {
                            return vue.openBlock(), vue.createElementBlock("view", {
                              key: b.orderId,
                              class: "bkrow"
                            }, [
                              vue.createElementVNode("view", { class: "bkleft" }, [
                                vue.createElementVNode(
                                  "text",
                                  { class: "bktime" },
                                  vue.toDisplayString($setup.bookingText(b)),
                                  1
                                  /* TEXT */
                                ),
                                vue.createElementVNode(
                                  "text",
                                  { class: "bksub" },
                                  "订单 #" + vue.toDisplayString(b.orderId) + vue.toDisplayString($setup.deviceText(b)),
                                  1
                                  /* TEXT */
                                )
                              ]),
                              vue.createElementVNode(
                                "text",
                                {
                                  class: vue.normalizeClass(["tag", $setup.statusTag("order", b.orderStatus, "")])
                                },
                                vue.toDisplayString($setup.statusLabel("order", b.orderStatus, "")),
                                3
                                /* TEXT, CLASS */
                              )
                            ]);
                          }),
                          128
                          /* KEYED_FRAGMENT */
                        )),
                        vue.createElementVNode(
                          "text",
                          { class: "bkfoot" },
                          "共 " + vue.toDisplayString($setup.box.list.length) + " 段被占用，其余时段空闲",
                          1
                          /* TEXT */
                        )
                      ],
                      64
                      /* STABLE_FRAGMENT */
                    ))
                  ])) : vue.createCommentVNode("v-if", true)
                ]);
              }),
              128
              /* KEYED_FRAGMENT */
            )),
            vue.createElementVNode("text", { class: "tip" }, " 点任意场地可展开它的「已占用时段」；占用口径与下单判重一致（待确认 / 已确认都算占用）。 ")
          ],
          64
          /* STABLE_FRAGMENT */
        ))
      ])
    ]);
  }
  const PagesSpaceList = /* @__PURE__ */ _export_sfc(_sfc_main$3, [["render", _sfc_render$2], ["__scopeId", "data-v-7bd4c190"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/space/list.vue"]]);
  const _sfc_main$2 = {
    __name: "capture",
    setup(__props, { expose: __expose }) {
      __expose();
      const photo = vue.ref("");
      const result = vue.ref(null);
      const analyzing = vue.ref(false);
      const spaceList = vue.ref([]);
      const spaceIndex = vue.ref(-1);
      const spaceLabel2 = vue.computed(() => {
        if (spaceIndex.value < 0 || !spaceList.value.length)
          return "未选择";
        return spaceName(spaceList.value[spaceIndex.value]) || "未选择";
      });
      const confidenceText = vue.computed(() => {
        const c = result.value ? result.value.confidence : null;
        if (c === void 0 || c === null || c === "")
          return "";
        const n = Number(c);
        if (isNaN(n))
          return "";
        const pct = n <= 1 ? Math.round(n * 100) : Math.round(n);
        return `置信度 ${pct}%`;
      });
      const deviceName = vue.computed(() => {
        const r = result.value;
        if (!r)
          return "";
        return r.deviceName || r.deviceCode || "";
      });
      onLoad(() => {
        loadSpaces();
      });
      onUnload(() => resetLoading());
      async function loadSpaces() {
        try {
          const res = await spaces({ page: 1, pageSize: 50 });
          spaceList.value = res.list;
          if (spaceList.value.length)
            spaceIndex.value = 0;
        } catch (e) {
          spaceList.value = [];
        }
      }
      function onSpaceChange(e) {
        const index = Number(e && e.detail && e.detail.value);
        if (Number.isInteger(index) && index >= 0 && index < spaceList.value.length) {
          spaceIndex.value = index;
        }
      }
      function onPicked(path, size) {
        if (!validate(path, size))
          return;
        photo.value = path;
        result.value = null;
        analyze2(path);
      }
      function chooseImage(source, onPickedCb) {
        const sourceType = Array.isArray(source) ? source : [source];
        let retried = false;
        const onFail = (err) => {
          const msg = String(err && err.errMsg || "");
          if (/cancel/i.test(msg))
            return;
          if (!retried) {
            retried = true;
            chooseImageLegacy(sourceType, onPickedCb, onFail);
            return;
          }
          toast(msg ? `打开失败：${msg}` : "打开失败，请重试");
        };
        if (typeof uni.chooseMedia === "function") {
          uni.chooseMedia({
            count: 1,
            mediaType: ["image"],
            sourceType,
            sizeType: ["compressed"],
            camera: "back",
            success: (res) => {
              const f = res.tempFiles && res.tempFiles[0];
              if (f)
                onPickedCb(f.tempFilePath, f.size);
            },
            fail: onFail
          });
          return;
        }
        chooseImageLegacy(sourceType, onPickedCb, onFail);
      }
      function chooseImageLegacy(sourceType, onPickedCb, onFail) {
        uni.chooseImage({
          count: 1,
          sizeType: ["compressed"],
          sourceType,
          success: (res) => {
            const path = res.tempFilePaths && res.tempFilePaths[0];
            const file = res.tempFiles && res.tempFiles[0];
            if (path)
              onPickedCb(path, file ? file.size : 0);
          },
          fail: onFail
        });
      }
      function pick2() {
        if (analyzing.value)
          return;
        chooseImage(["camera", "album"], onPicked);
      }
      function validate(path, size) {
        if (size && size > IMAGE_LIMIT.MAX_MB * 1024 * 1024) {
          toast(`图片不能超过 ${IMAGE_LIMIT.MAX_MB}MB`);
          return false;
        }
        const m = String(path).match(/\.([a-zA-Z0-9]+)(?:\?|$)/);
        if (m) {
          const ext = m[1].toLowerCase();
          if (IMAGE_LIMIT.EXT.indexOf(ext) < 0) {
            toast(`仅支持 ${IMAGE_LIMIT.EXT.join(" / ")}`);
            return false;
          }
        }
        return true;
      }
      async function analyze2(path) {
        analyzing.value = true;
        showLoading("AI 识别中…");
        try {
          const spaceId = spaceIndex.value >= 0 && spaceList.value[spaceIndex.value] ? first(spaceList.value[spaceIndex.value].spaceId, spaceList.value[spaceIndex.value].id) : void 0;
          result.value = await submit(path, spaceId);
        } catch (e) {
          toast(e.message || "识别失败，请换一张照片试试");
          result.value = null;
        } finally {
          analyzing.value = false;
          hideLoading();
        }
      }
      function goTickets() {
        uni.reLaunch({ url: TABS[2].path });
      }
      const __returned__ = { photo, result, analyzing, spaceList, spaceIndex, spaceLabel: spaceLabel2, confidenceText, deviceName, loadSpaces, onSpaceChange, onPicked, chooseImage, chooseImageLegacy, pick: pick2, validate, analyze: analyze2, goTickets, ref: vue.ref, computed: vue.computed, get onLoad() {
        return onLoad;
      }, get onUnload() {
        return onUnload;
      }, get submit() {
        return submit;
      }, get fetchSpaces() {
        return spaces;
      }, get statusLabel() {
        return statusLabel;
      }, get statusTag() {
        return statusTag;
      }, get first() {
        return first;
      }, get spaceName() {
        return spaceName;
      }, get IMAGE_LIMIT() {
        return IMAGE_LIMIT;
      }, get toast() {
        return toast;
      }, get showLoading() {
        return showLoading;
      }, get hideLoading() {
        return hideLoading;
      }, get resetLoading() {
        return resetLoading;
      }, get TABS() {
        return TABS;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render$1(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "拍照巡检",
        back: "",
        right: $setup.spaceLabel
      }, null, 8, ["right"]),
      vue.createElementVNode("view", { class: "app-body has-cta" }, [
        vue.createElementVNode("view", {
          class: "imgbox",
          onClick: $setup.pick
        }, [
          $setup.photo ? (vue.openBlock(), vue.createElementBlock("image", {
            key: 0,
            class: "photo",
            src: $setup.photo,
            mode: "aspectFill"
          }, null, 8, ["src"])) : (vue.openBlock(), vue.createElementBlock("view", {
            key: 1,
            class: "cam"
          }, [
            vue.createElementVNode("text", { class: "big" }, "📷"),
            vue.createElementVNode("text", null, "点击拍照，或从相册选择")
          ])),
          $setup.photo ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 2,
            class: "bbox on-photo"
          }, [
            vue.createElementVNode("view", { class: "cn" }),
            vue.createElementVNode("view", { class: "cn" }),
            vue.createElementVNode("view", { class: "cn" }),
            vue.createElementVNode("view", { class: "cn" })
          ])) : vue.createCommentVNode("v-if", true),
          $setup.analyzing ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 3,
            class: "scanline"
          })) : vue.createCommentVNode("v-if", true)
        ]),
        vue.createElementVNode("view", { class: "mcard" }, [
          vue.createElementVNode("picker", {
            range: $setup.spaceList,
            "range-key": "spaceName",
            onChange: $setup.onSpaceChange
          }, [
            vue.createElementVNode("view", { class: "mbrow pick" }, [
              vue.createElementVNode("text", { class: "k" }, "巡检区域"),
              vue.createElementVNode(
                "text",
                { class: "v" },
                vue.toDisplayString($setup.spaceLabel),
                1
                /* TEXT */
              ),
              vue.createElementVNode("text", { class: "ma" }, "›")
            ])
          ], 40, ["range"])
        ]),
        $setup.result ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 0,
          class: "mcard"
        }, [
          vue.createElementVNode("view", { class: "mtitle" }, [
            vue.createElementVNode("text", null, "🤖 AI 识别结果"),
            $setup.confidenceText ? (vue.openBlock(), vue.createElementBlock(
              "text",
              {
                key: 0,
                class: "more"
              },
              vue.toDisplayString($setup.confidenceText),
              1
              /* TEXT */
            )) : vue.createCommentVNode("v-if", true)
          ]),
          vue.createElementVNode("view", { class: "mbrow" }, [
            vue.createElementVNode("text", { class: "k" }, "设备状态"),
            vue.createElementVNode("text", { class: "v" }, [
              vue.createElementVNode(
                "text",
                {
                  class: vue.normalizeClass(["tag", $setup.statusTag("device", $setup.result.deviceStatus, $setup.result.deviceStatusText)])
                },
                vue.toDisplayString($setup.statusLabel("device", $setup.result.deviceStatus, $setup.result.deviceStatusText)),
                3
                /* TEXT, CLASS */
              )
            ])
          ]),
          $setup.deviceName ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 0,
            class: "mbrow"
          }, [
            vue.createElementVNode("text", { class: "k" }, "设备编号"),
            vue.createElementVNode(
              "text",
              { class: "v" },
              vue.toDisplayString($setup.deviceName),
              1
              /* TEXT */
            )
          ])) : vue.createCommentVNode("v-if", true),
          vue.createElementVNode("view", { class: "mbrow" }, [
            vue.createElementVNode("text", { class: "k" }, "关联空间"),
            vue.createElementVNode(
              "text",
              { class: "v" },
              vue.toDisplayString($setup.spaceLabel),
              1
              /* TEXT */
            )
          ]),
          $setup.result.repairSuggestion ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 1,
            class: "mbrow"
          }, [
            vue.createElementVNode("text", { class: "k" }, "维修建议"),
            vue.createElementVNode(
              "text",
              { class: "v" },
              vue.toDisplayString($setup.result.repairSuggestion),
              1
              /* TEXT */
            )
          ])) : vue.createCommentVNode("v-if", true)
        ])) : vue.createCommentVNode("v-if", true),
        $setup.result && $setup.result.report ? (vue.openBlock(), vue.createElementBlock("view", {
          key: 1,
          class: "mcard"
        }, [
          vue.createElementVNode("view", { class: "mtitle" }, "📋 AI 巡检摘要"),
          vue.createElementVNode(
            "text",
            { class: "mtext" },
            vue.toDisplayString($setup.result.report),
            1
            /* TEXT */
          )
        ])) : vue.createCommentVNode("v-if", true),
        !$setup.photo ? (vue.openBlock(), vue.createElementBlock(
          "text",
          {
            key: 2,
            class: "note"
          },
          " 支持 jpg / png / webp / bmp，单张不超过 " + vue.toDisplayString($setup.IMAGE_LIMIT.MAX_MB) + "MB。 ",
          1
          /* TEXT */
        )) : vue.createCommentVNode("v-if", true)
      ]),
      vue.createElementVNode("view", { class: "app-cta" }, [
        !$setup.result ? (vue.openBlock(), vue.createElementBlock(
          "view",
          {
            key: 0,
            class: vue.normalizeClass(["btn ai block", { disabled: $setup.analyzing }]),
            "hover-class": "btn-on",
            "hover-stay-time": 60,
            onClick: $setup.pick
          },
          vue.toDisplayString($setup.analyzing ? "AI 识别中…" : "拍一张开始巡检"),
          3
          /* TEXT, CLASS */
        )) : (vue.openBlock(), vue.createElementBlock(
          "view",
          {
            key: 1,
            class: "btn warn block",
            "hover-class": "btn-on",
            "hover-stay-time": 60,
            onClick: $setup.goTickets
          },
          "查看维修工单 #" + vue.toDisplayString($setup.result.ticketId),
          1
          /* TEXT */
        ))
      ])
    ]);
  }
  const PagesInspectCapture = /* @__PURE__ */ _export_sfc(_sfc_main$2, [["render", _sfc_render$1], ["__scopeId", "data-v-87facfe1"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/inspect/capture.vue"]]);
  const _sfc_main$1 = {
    __name: "detail",
    setup(__props, { expose: __expose }) {
      __expose();
      const order = vue.ref(null);
      const loading = vue.ref(true);
      const error = vue.ref("");
      const showTrace = vue.ref(false);
      const wantId = vue.ref("");
      const rangeText = vue.computed(() => {
        if (!order.value)
          return "";
        return formatTimeRange(order.value.startTime, order.value.endTime) || "—";
      });
      const orderNoText = vue.computed(() => {
        const id = orderId(order.value);
        return id === void 0 ? "—" : "#" + id;
      });
      const budgetText = vue.computed(() => {
        const o = order.value;
        if (!o)
          return "—";
        return formatMoney(spaceBudget(o.spaceId)) || "—";
      });
      const durationText = vue.computed(() => {
        if (!order.value)
          return "";
        return formatDuration(order.value.startTime, order.value.endTime);
      });
      const deviceText = vue.computed(() => deviceLabel(order.value && order.value.deviceIds));
      const canCancel = vue.computed(() => {
        if (!order.value)
          return false;
        return canCancelOrder(orderStatus(order.value), orderStatusText(order.value));
      });
      const canComplete = vue.computed(() => {
        if (!order.value)
          return false;
        return canCompleteOrder(orderStatus(order.value), orderStatusText(order.value));
      });
      const canConfirm = vue.computed(() => {
        if (!order.value)
          return false;
        return canConfirmOrder(orderStatus(order.value), orderStatusText(order.value));
      });
      const trace = vue.computed(() => {
        const raw = order.value && order.value.agentTrace;
        if (!Array.isArray(raw))
          return [];
        return raw.map((t, i) => ({
          step: t.step === void 0 || t.step === null ? i + 1 : t.step,
          title: t.result || `步骤 ${i + 1}`,
          time: (t.timestamp || "").slice(11),
          action: t.action || ""
        }));
      });
      async function load() {
        loading.value = true;
        error.value = "";
        try {
          order.value = await getOrder(wantId.value);
        } catch (e) {
          error.value = e && e.code === 40404 ? "预约不存在或无权查看" : e.message || "加载失败";
          order.value = null;
        } finally {
          loading.value = false;
        }
      }
      onLoad((options) => {
        ensureNameMaps();
        wantId.value = options && options.orderId || "";
        if (!wantId.value) {
          loading.value = false;
          error.value = "缺少预约编号";
          return;
        }
        load();
      });
      async function askCancel() {
        const ok = await confirm({
          content: `确定取消「${spaceLabel(order.value.spaceId)}」的预约吗？取消后时段将释放给其他人。`,
          title: "取消预约",
          confirmText: "确定取消",
          confirmColor: "#F56C6C"
        });
        if (!ok)
          return;
        try {
          await cancelOrder(wantId.value);
          toastOk("已取消");
          load();
        } catch (e) {
          toast(e.message || "取消失败");
          load();
        }
      }
      async function askConfirm() {
        const ok = await confirm({
          content: `确认「${spaceLabel(order.value.spaceId)}」这场预约吗？确认后该时段正式占用。`,
          title: "确认预约",
          confirmText: "确认预约"
        });
        if (!ok)
          return;
        try {
          await confirmOrder(wantId.value);
          toastOk("已确认");
          load();
        } catch (e) {
          toast(e.message || "确认失败");
          load();
        }
      }
      async function askComplete() {
        const ok = await confirm({
          content: `确认「${spaceLabel(order.value.spaceId)}」这场预约已经结束了吗？完成后该时段会释放给其他人。`,
          title: "标记完成",
          confirmText: "标记完成"
        });
        if (!ok)
          return;
        try {
          await completeOrder(wantId.value);
          toastOk("已完成");
          load();
        } catch (e) {
          toast(e.message || "操作失败");
          load();
        }
      }
      function goList() {
        uni.reLaunch({ url: TABS[1].path });
      }
      const __returned__ = { order, loading, error, showTrace, wantId, rangeText, orderNoText, budgetText, durationText, deviceText, canCancel, canComplete, canConfirm, trace, load, askCancel, askConfirm, askComplete, goList, ref: vue.ref, computed: vue.computed, get onLoad() {
        return onLoad;
      }, get getOrder() {
        return getOrder;
      }, get cancelOrder() {
        return cancelOrder;
      }, get completeOrder() {
        return completeOrder;
      }, get confirmOrder() {
        return confirmOrder;
      }, get statusLabel() {
        return statusLabel;
      }, get statusTag() {
        return statusTag;
      }, get canCancelOrder() {
        return canCancelOrder;
      }, get canCompleteOrder() {
        return canCompleteOrder;
      }, get canConfirmOrder() {
        return canConfirmOrder;
      }, get ensureNameMaps() {
        return ensureNameMaps;
      }, get deviceLabel() {
        return deviceLabel;
      }, get spaceLabel() {
        return spaceLabel;
      }, get spaceBudget() {
        return spaceBudget;
      }, get orderStatus() {
        return orderStatus;
      }, get orderStatusText() {
        return orderStatusText;
      }, get orderId() {
        return orderId;
      }, get formatTimeRange() {
        return formatTimeRange;
      }, get formatDuration() {
        return formatDuration;
      }, get formatMoney() {
        return formatMoney;
      }, get confirm() {
        return confirm;
      }, get toast() {
        return toast;
      }, get toastOk() {
        return toastOk;
      }, get TABS() {
        return TABS;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  function _sfc_render(_ctx, _cache, $props, $setup, $data, $options) {
    const _component_mp_nav_bar = resolveEasycom(vue.resolveDynamicComponent("mp-nav-bar"), __easycom_0);
    const _component_mp_empty = resolveEasycom(vue.resolveDynamicComponent("mp-empty"), __easycom_1);
    return vue.openBlock(), vue.createElementBlock("view", { class: "app-page" }, [
      vue.createVNode(_component_mp_nav_bar, {
        title: "预约详情",
        back: ""
      }),
      vue.createElementVNode(
        "view",
        {
          class: vue.normalizeClass(["app-body", { "has-cta": $setup.canCancel }])
        },
        [
          $setup.loading ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 0,
            class: "mcard"
          }, [
            vue.createElementVNode("text", { class: "mtext" }, "加载中…")
          ])) : !$setup.order ? (vue.openBlock(), vue.createBlock(_component_mp_empty, {
            key: 1,
            icon: "🔍",
            text: $setup.error || "没有找到这条预约，可能已被取消",
            "action-text": "返回列表",
            onAction: $setup.goList
          }, null, 8, ["text"])) : (vue.openBlock(), vue.createElementBlock(
            vue.Fragment,
            { key: 2 },
            [
              vue.createElementVNode("view", { class: "plan head" }, [
                vue.createElementVNode(
                  "text",
                  { class: "tt" },
                  vue.toDisplayString($setup.spaceLabel($setup.order.spaceId)),
                  1
                  /* TEXT */
                ),
                vue.createElementVNode(
                  "text",
                  { class: "dd" },
                  vue.toDisplayString($setup.rangeText),
                  1
                  /* TEXT */
                ),
                vue.createElementVNode("view", { class: "tags" }, [
                  vue.createElementVNode(
                    "text",
                    {
                      class: vue.normalizeClass(["tag", $setup.statusTag("order", $setup.orderStatus($setup.order), $setup.orderStatusText($setup.order))])
                    },
                    vue.toDisplayString($setup.statusLabel("order", $setup.orderStatus($setup.order), $setup.orderStatusText($setup.order))),
                    3
                    /* TEXT, CLASS */
                  ),
                  $setup.durationText ? (vue.openBlock(), vue.createElementBlock(
                    "text",
                    {
                      key: 0,
                      class: "tag gray"
                    },
                    vue.toDisplayString($setup.durationText),
                    1
                    /* TEXT */
                  )) : vue.createCommentVNode("v-if", true)
                ])
              ]),
              vue.createElementVNode("view", { class: "mcard" }, [
                vue.createElementVNode("view", { class: "mtitle" }, "预约信息"),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "单号"),
                  vue.createElementVNode(
                    "text",
                    { class: "v mono" },
                    vue.toDisplayString($setup.orderNoText),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "场地"),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString($setup.spaceLabel($setup.order.spaceId)),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "时段"),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString($setup.rangeText),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "设备"),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString($setup.deviceText),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "场地预算"),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString($setup.budgetText),
                    1
                    /* TEXT */
                  )
                ]),
                vue.createElementVNode("view", { class: "mbrow" }, [
                  vue.createElementVNode("text", { class: "k" }, "创建于"),
                  vue.createElementVNode(
                    "text",
                    { class: "v" },
                    vue.toDisplayString($setup.order.createTime || "—"),
                    1
                    /* TEXT */
                  )
                ])
              ]),
              $setup.order.agentRequest ? (vue.openBlock(), vue.createElementBlock("view", {
                key: 0,
                class: "mcard"
              }, [
                vue.createElementVNode("view", { class: "mtitle" }, "🗣 原始需求"),
                vue.createElementVNode(
                  "text",
                  { class: "mtext" },
                  vue.toDisplayString($setup.order.agentRequest),
                  1
                  /* TEXT */
                )
              ])) : vue.createCommentVNode("v-if", true),
              $setup.trace.length ? (vue.openBlock(), vue.createElementBlock("view", {
                key: 1,
                class: "mcard"
              }, [
                vue.createElementVNode("view", { class: "mtitle" }, [
                  vue.createElementVNode("text", null, "🧠 Agent 决策链"),
                  vue.createElementVNode(
                    "text",
                    {
                      class: "more",
                      onClick: _cache[0] || (_cache[0] = ($event) => $setup.showTrace = !$setup.showTrace)
                    },
                    vue.toDisplayString($setup.showTrace ? "收起" : `展开 ${$setup.trace.length} 步`),
                    1
                    /* TEXT */
                  )
                ]),
                $setup.showTrace ? (vue.openBlock(true), vue.createElementBlock(
                  vue.Fragment,
                  { key: 0 },
                  vue.renderList($setup.trace, (t) => {
                    return vue.openBlock(), vue.createElementBlock("view", {
                      key: t.step,
                      class: "mbstep"
                    }, [
                      vue.createElementVNode(
                        "view",
                        { class: "tnum" },
                        vue.toDisplayString(t.step),
                        1
                        /* TEXT */
                      ),
                      vue.createElementVNode("view", { class: "txt" }, [
                        vue.createElementVNode("view", { class: "sline" }, [
                          vue.createElementVNode(
                            "text",
                            { class: "ss" },
                            vue.toDisplayString(t.title),
                            1
                            /* TEXT */
                          ),
                          !t.action ? (vue.openBlock(), vue.createElementBlock("text", {
                            key: 0,
                            class: "tag gray"
                          }, "推理")) : vue.createCommentVNode("v-if", true)
                        ]),
                        t.time ? (vue.openBlock(), vue.createElementBlock(
                          "text",
                          {
                            key: 0,
                            class: "stime"
                          },
                          vue.toDisplayString(t.time),
                          1
                          /* TEXT */
                        )) : vue.createCommentVNode("v-if", true)
                      ])
                    ]);
                  }),
                  128
                  /* KEYED_FRAGMENT */
                )) : vue.createCommentVNode("v-if", true)
              ])) : vue.createCommentVNode("v-if", true)
            ],
            64
            /* STABLE_FRAGMENT */
          ))
        ],
        2
        /* CLASS */
      ),
      $setup.canConfirm ? (vue.openBlock(), vue.createElementBlock("view", {
        key: 0,
        class: "app-cta"
      }, [
        vue.createElementVNode("view", { class: "app-cta-row" }, [
          vue.createElementVNode("view", {
            class: "btn grow",
            "hover-class": "btn-on",
            onClick: $setup.askConfirm
          }, "确认预约"),
          $setup.canCancel ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 0,
            class: "btn ghost danger",
            "hover-class": "btn-on",
            onClick: $setup.askCancel
          }, "取消预约")) : vue.createCommentVNode("v-if", true)
        ])
      ])) : $setup.canComplete ? (vue.openBlock(), vue.createElementBlock("view", {
        key: 1,
        class: "app-cta"
      }, [
        vue.createElementVNode("view", { class: "app-cta-row" }, [
          vue.createElementVNode("view", {
            class: "btn grow",
            "hover-class": "btn-on",
            onClick: $setup.askComplete
          }, "标记完成"),
          $setup.canCancel ? (vue.openBlock(), vue.createElementBlock("view", {
            key: 0,
            class: "btn ghost danger",
            "hover-class": "btn-on",
            onClick: $setup.askCancel
          }, "取消预约")) : vue.createCommentVNode("v-if", true)
        ])
      ])) : $setup.canCancel ? (vue.openBlock(), vue.createElementBlock("view", {
        key: 2,
        class: "app-cta"
      }, [
        vue.createElementVNode("view", {
          class: "btn ghost block danger",
          "hover-class": "btn-on",
          onClick: $setup.askCancel
        }, "取消预约")
      ])) : vue.createCommentVNode("v-if", true)
    ]);
  }
  const PagesOrderDetail = /* @__PURE__ */ _export_sfc(_sfc_main$1, [["render", _sfc_render], ["__scopeId", "data-v-6b23c96c"], ["__file", "F:/project_summary/Scheduling_Platform/miniprogram/pages/order/detail.vue"]]);
  __definePage("pages/index/index", PagesIndexIndex);
  __definePage("pages/order/list", PagesOrderList);
  __definePage("pages/inspect/index", PagesInspectIndex);
  __definePage("pages/message/list", PagesMessageList);
  __definePage("pages/mine/index", PagesMineIndex);
  __definePage("pages/login/index", PagesLoginIndex);
  __definePage("pages/voice/record", PagesVoiceRecord);
  __definePage("pages/agent/thinking", PagesAgentThinking);
  __definePage("pages/agent/plan", PagesAgentPlan);
  __definePage("pages/space/recognize", PagesSpaceRecognize);
  __definePage("pages/space/list", PagesSpaceList);
  __definePage("pages/inspect/capture", PagesInspectCapture);
  __definePage("pages/order/detail", PagesOrderDetail);
  const _sfc_main = {
    __name: "App",
    setup(__props, { expose: __expose }) {
      __expose();
      onLaunch(() => {
        restoreSession();
      });
      const __returned__ = { get onLaunch() {
        return onLaunch;
      }, get restoreSession() {
        return restoreSession;
      } };
      Object.defineProperty(__returned__, "__isScriptSetup", { enumerable: false, value: true });
      return __returned__;
    }
  };
  const App = /* @__PURE__ */ _export_sfc(_sfc_main, [["__file", "F:/project_summary/Scheduling_Platform/miniprogram/App.vue"]]);
  function createApp() {
    const app = vue.createVueApp(App);
    return { app };
  }
  const { app: __app__, Vuex: __Vuex__, Pinia: __Pinia__ } = createApp();
  uni.Vuex = __Vuex__;
  uni.Pinia = __Pinia__;
  __app__.provide("__globalStyles", __uniConfig.styles);
  __app__._component.mpType = "app";
  __app__._component.render = () => {
  };
  __app__.mount("#app");
})(Vue);
