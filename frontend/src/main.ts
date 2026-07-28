import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { captureLaunchToken } from "./session/captureLaunchToken.ts";
import "./styles.css";
import "./liquid-glass.css";

const accessToken = captureLaunchToken();

createApp(App, { accessToken })
  .use(createPinia())
  .mount("#app");
