<script setup lang="ts">
import { useGlassFilterDescriptors } from "@/glass/filterRuntime.ts";

const runtimeFilters = useGlassFilterDescriptors();
const capsuleMap = [
  "data:image/svg+xml,",
  "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 48'%3E",
  "%3Cdefs%3E%3CradialGradient id='g'%3E",
  "%3Cstop offset='0' stop-color='%23808080'/%3E",
  "%3Cstop offset='.68' stop-color='%23808080'/%3E",
  "%3Cstop offset='1' stop-color='%23906f90'/%3E",
  "%3C/radialGradient%3E%3C/defs%3E",
  "%3Crect width='120' height='48' rx='24' fill='url(%23g)'/%3E",
  "%3C/svg%3E",
].join("");

const roundedMap = [
  "data:image/svg+xml,",
  "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 72'%3E",
  "%3Cdefs%3E%3CradialGradient id='g'%3E",
  "%3Cstop offset='0' stop-color='%23808080'/%3E",
  "%3Cstop offset='.72' stop-color='%23808080'/%3E",
  "%3Cstop offset='1' stop-color='%23926e8d'/%3E",
  "%3C/radialGradient%3E%3C/defs%3E",
  "%3Crect width='120' height='72' rx='18' fill='url(%23g)'/%3E",
  "%3C/svg%3E",
].join("");

const panelMap = [
  "data:image/svg+xml,",
  "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 160 120'%3E",
  "%3Cdefs%3E%3CradialGradient id='g'%3E",
  "%3Cstop offset='0' stop-color='%23808080'/%3E",
  "%3Cstop offset='.78' stop-color='%23808080'/%3E",
  "%3Cstop offset='1' stop-color='%238b7588'/%3E",
  "%3C/radialGradient%3E%3C/defs%3E",
  "%3Crect width='160' height='120' rx='22' fill='url(%23g)'/%3E",
  "%3C/svg%3E",
].join("");
</script>

<template>
  <svg
    class="liquid-glass-defs"
    data-liquid-glass-defs="v3"
    aria-hidden="true"
    width="0"
    height="0"
    focusable="false"
  >
    <defs>
      <filter
        id="liquid-glass-capsule"
        x="-10%"
        y="-25%"
        width="120%"
        height="150%"
        color-interpolation-filters="sRGB"
      >
        <feImage
          :href="capsuleMap"
          preserveAspectRatio="none"
          result="displacement"
        />
        <feDisplacementMap
          in="SourceGraphic"
          in2="displacement"
          scale="7"
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>
      <filter
        id="liquid-glass-rounded"
        x="-8%"
        y="-14%"
        width="116%"
        height="128%"
        color-interpolation-filters="sRGB"
      >
        <feImage
          :href="roundedMap"
          preserveAspectRatio="none"
          result="displacement"
        />
        <feDisplacementMap
          in="SourceGraphic"
          in2="displacement"
          scale="5"
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>
      <filter
        id="liquid-glass-panel"
        x="-6%"
        y="-8%"
        width="112%"
        height="116%"
        color-interpolation-filters="sRGB"
      >
        <feImage
          :href="panelMap"
          preserveAspectRatio="none"
          result="displacement"
        />
        <feDisplacementMap
          in="SourceGraphic"
          in2="displacement"
          scale="3"
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>
      <filter
        v-for="descriptor in runtimeFilters"
        :id="descriptor.filterId"
        :key="descriptor.key"
        x="-18%"
        y="-24%"
        width="136%"
        height="148%"
        color-interpolation-filters="sRGB"
        data-glass-dynamic-filter=""
        :data-glass-normal-map="descriptor.key"
      >
        <feImage
          :href="descriptor.dataUrl"
          preserveAspectRatio="none"
          result="displacement"
        />
        <feDisplacementMap
          in="SourceGraphic"
          in2="displacement"
          :scale="descriptor.displacement"
          xChannelSelector="R"
          yChannelSelector="G"
        />
      </filter>
    </defs>
  </svg>
</template>
