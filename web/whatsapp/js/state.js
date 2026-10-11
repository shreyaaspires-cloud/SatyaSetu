/**
 * state.js - Reactive State Store for WhatsApp Demo
 */

import { INITIAL_CHATS } from './data/seed.js';

class StateStore {
  constructor() {
    this.chats = JSON.parse(JSON.stringify(INITIAL_CHATS));
    this.activeChatId = "sharma";
    this.activeFilter = "all";
    this.searchQuery = "";
    this.lastPresenterData = null;
    this.isPresenterOpen = false;
    this.listeners = new Set();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    for (const listener of this.listeners) {
      try {
        listener(this);
      } catch (err) {
        console.error("State listener error:", err);
      }
    }
  }

  getActiveChat() {
    return this.chats[this.activeChatId];
  }

  setActiveChat(id) {
    if (this.chats[id]) {
      this.activeChatId = id;
      // Mark as read
      this.chats[id].unread = 0;
      this.notify();
    }
  }

  setFilter(filter) {
    this.activeFilter = filter;
    this.notify();
  }

  setSearchQuery(q) {
    this.searchQuery = q.toLowerCase().trim();
    this.notify();
  }

  addMessage(chatId, message) {
    if (!this.chats[chatId]) return;
    this.chats[chatId].messages.push(message);
    this.chats[chatId].lastMsg = (message.isMe ? "You: " : "") + (message.text ? message.text.substring(0, 40) : "Media");
    this.chats[chatId].time = message.time || "Just now";
    this.notify();
  }

  updateMessage(chatId, messageId, updates) {
    if (!this.chats[chatId]) return;
    const msg = this.chats[chatId].messages.find(m => m.id === messageId);
    if (msg) {
      Object.assign(msg, updates);
      this.notify();
    }
  }

  deleteMessage(chatId, messageId) {
    if (!this.chats[chatId]) return;
    this.chats[chatId].messages = this.chats[chatId].messages.filter(m => m.id !== messageId);
    this.notify();
  }

  setPresenterData(data) {
    this.lastPresenterData = data;
    this.notify();
  }

  togglePresenter(force) {
    this.isPresenterOpen = force !== undefined ? force : !this.isPresenterOpen;
    this.notify();
  }
}

export const store = new StateStore();
