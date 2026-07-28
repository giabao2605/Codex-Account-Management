import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import tseslint from "typescript-eslint";
import vueParser from "vue-eslint-parser";

export default [
  {
    ignores: [
      "coverage/**",
      "playwright-report/**",
      "test-results/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  {
    languageOptions: {
      globals: {
        document: "readonly",
        cancelAnimationFrame: "readonly",
        clearTimeout: "readonly",
        HTMLCanvasElement: "readonly",
        HTMLButtonElement: "readonly",
        HTMLElement: "readonly",
        KeyboardEvent: "readonly",
        MessageEvent: "readonly",
        navigator: "readonly",
        Node: "readonly",
        PointerEvent: "readonly",
        requestAnimationFrame: "readonly",
        URL: "readonly",
        WebGL2RenderingContext: "readonly",
        WebGLBuffer: "readonly",
        WebGLProgram: "readonly",
        WebGLShader: "readonly",
        WebGLUniformLocation: "readonly",
        Worker: "readonly",
        window: "readonly",
        Window: "readonly",
      },
    },
    rules: {
      "vue/max-attributes-per-line": "off",
      "vue/singleline-html-element-content-newline": "off",
    },
  },
  {
    files: ["**/*.vue"],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: "latest",
        sourceType: "module",
        extraFileExtensions: [".vue"],
      },
    },
  },
];
