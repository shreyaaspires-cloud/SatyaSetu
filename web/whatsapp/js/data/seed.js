/**
 * seed.js - Fictional Chat Seed Data (F7, Section 6.2)
 * Contains realistic Indian family, community, and society conversations.
 * Strictly zero real personal identities or public figures.
 */

export const INITIAL_CHATS = {
  bot: {
    id: "bot",
    name: "SatyaSetu",
    sub: "Official Business Account · AI Fact Checker",
    avatar: "🛡️",
    color: "linear-gradient(135deg, #00a884, #00796b)",
    isBot: true,
    pinned: true,
    unread: 0,
    time: "Today",
    lastMsg: "Official Fact-Check Assistant ready.",
    messages: [
      {
        id: "b1",
        sender: "SatyaSetu",
        isMe: false,
        text: "*SatyaSetu Fact-Check Assistant*\n\nForward any viral message, health rumor, policy claim, or upload a circular screenshot/audio to verify against authoritative fact-checkers (IFCN, PIB, WHO, Wikipedia).",
        time: "Today",
        status: ""
      }
    ]
  },
  sharma: {
    id: "sharma",
    name: "Sharma Parivar 🏠",
    sub: "Mummy, Papa, Dadi, Rohan, You",
    avatar: "🏠",
    color: "#0f766e",
    isBot: false,
    pinned: false,
    unread: 2,
    time: "9:02 am",
    lastMsg: "Papa: Haan beta, pehle verify kar lo.",
    messages: [
      {
        id: "m_sharma_1",
        sender: "Mummy",
        isMe: false,
        forwarded: "many",
        text: "नींबू का रस और गर्म पानी पीने से 48 घंटे में कैंसर ठीक हो जाता है! सभी ग्रुप में शेयर करें 🙏",
        time: "8:59 am",
        status: ""
      },
      {
        id: "m_sharma_2",
        sender: "You",
        isMe: true,
        quoted: {
          author: "Mummy",
          text: "नींबू का रस और गर्म पानी पीने से 48 घंटे में कैंसर ठीक हो जाता है..."
        },
        text: "Mummy, aise unverified forwards pe vishwas mat karo. Main SatyaSetu se check karta hoon.",
        time: "9:00 am",
        status: "✓✓"
      },
      {
        id: "m_sharma_3",
        sender: "Papa",
        isMe: false,
        text: "Haan beta, pehle verify kar lo.",
        time: "9:02 am",
        status: ""
      }
    ]
  },
  rishtedar: {
    id: "rishtedar",
    name: "Rishtedar Mandali 👨‍👩‍👧‍👦",
    sub: "Mausi, Mama ji, Chachu, Bua, You",
    avatar: "👨‍👩‍👧‍👦",
    color: "#b45309",
    isBot: false,
    pinned: false,
    unread: 1,
    time: "Yesterday",
    lastMsg: "Mama ji: Is this real? I transfer via UPI daily.",
    messages: [
      {
        id: "m_rish_1",
        sender: "Mausi",
        isMe: false,
        forwarded: "many",
        text: "NPCI has introduced 2 percent transaction fee on normal UPI payments starting this week. Forward to everyone before midnight!",
        time: "Yesterday",
        status: ""
      },
      {
        id: "m_rish_2",
        sender: "Mama ji",
        isMe: false,
        text: "Is this real? I transfer via UPI daily.",
        time: "Yesterday",
        status: ""
      }
    ]
  },
  society: {
    id: "society",
    name: "Shanti Nagar Society 🏢",
    sub: "Secretary Uncle, Mrs. Iyer, Flat 304, You",
    avatar: "🏢",
    color: "#334155",
    isBot: false,
    pinned: false,
    unread: 0,
    time: "Yesterday",
    lastMsg: "Secretary Uncle: Overhead water tank cleaning scheduled...",
    messages: [
      {
        id: "m_soc_1",
        sender: "Secretary Uncle",
        isMe: false,
        text: "Dear Residents, overhead water tank cleaning scheduled for Saturday 10:00 AM to 2:00 PM. Please store sufficient water.",
        time: "Yesterday",
        status: ""
      }
    ]
  },
  friends: {
    id: "friends",
    name: "Old School Gang 🎒",
    sub: "Arjun, Kabir, Priya, You",
    avatar: "🎒",
    color: "#701a75",
    isBot: false,
    pinned: false,
    unread: 0,
    time: "10:45 am",
    lastMsg: "Kabir: Anyone up for weekend football match?",
    messages: [
      {
        id: "m_fr_1",
        sender: "Kabir",
        isMe: false,
        text: "Anyone up for weekend football match?",
        time: "10:45 am",
        status: ""
      }
    ]
  },
  mummy: {
    id: "mummy",
    name: "Mummy ❤️",
    sub: "online",
    avatar: "❤️",
    color: "#be185d",
    isBot: false,
    pinned: false,
    unread: 0,
    time: "1:02 pm",
    lastMsg: "Beta lunch kar liya?",
    messages: [
      {
        id: "m_mum_1",
        sender: "Mummy",
        isMe: false,
        text: "Beta lunch kar liya?",
        time: "1:02 pm",
        status: ""
      }
    ]
  },
  papa: {
    id: "papa",
    name: "Papa 👔",
    sub: "last seen today at 11:15 am",
    avatar: "👔",
    color: "#1d4ed8",
    isBot: false,
    pinned: false,
    unread: 0,
    time: "11:15 am",
    lastMsg: "Someone sent a forward claiming free railway travel...",
    messages: [
      {
        id: "m_pap_1",
        sender: "Papa",
        isMe: false,
        text: "Someone sent a forward claiming free railway travel for senior citizens. Check if it is official.",
        time: "11:15 am",
        status: ""
      }
    ]
  }
};
