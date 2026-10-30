import {
  UserOutlined, TeamOutlined, IdcardOutlined, MailOutlined, GlobalOutlined,
  HddOutlined, PhoneOutlined, EnvironmentOutlined, GoogleOutlined,
  SendOutlined, MessageOutlined, WarningOutlined, AlertOutlined, LockOutlined,
  BankOutlined, WalletOutlined, BugOutlined, SearchOutlined, ApiOutlined,
  SafetyOutlined, PictureOutlined, LinkOutlined, CameraOutlined,
  FileImageOutlined, HeartOutlined, AuditOutlined, RocketOutlined,
  CompassOutlined, NumberOutlined, BarcodeOutlined,
} from '@ant-design/icons'
import type { ComponentType } from 'react'

/** Maltego-style icon per entity type. Falls back to a generic node icon. */
const MAP: Record<string, ComponentType<any>> = {
  // Transport assets. A ship and an aircraft are registered assets with an
  // owner, and their permanent identifiers get their own marks: those are
  // what survive a rename, a re-flagging or a change of registration.
  vessel: CompassOutlined,
  aircraft: RocketOutlined,
  imo_number: NumberOutlined,
  aircraft_serial: BarcodeOutlined,
  // A GLN is the same kind of thing: the number that outlives the name.
  gln: NumberOutlined,
  person: UserOutlined,
  social_account: TeamOutlined,
  username: IdcardOutlined,
  email_address: MailOutlined, email: MailOutlined,
  domain: GlobalOutlined,
  dns_a: GlobalOutlined, dns_aaaa: GlobalOutlined, dns_mx: GlobalOutlined,
  dns_ns: GlobalOutlined, dns_txt: GlobalOutlined, dns_cname: GlobalOutlined,
  ip: HddOutlined, ip_address: HddOutlined,
  phone: PhoneOutlined, phone_number: PhoneOutlined,
  location: EnvironmentOutlined,
  google_account: GoogleOutlined,
  telegram_channel: SendOutlined, telegram_message: SendOutlined,
  telegram_user: SendOutlined, telegram_media: PictureOutlined,
  discord_guild: MessageOutlined, discord_account: MessageOutlined,
  crime_forum: WarningOutlined, forum_hit: WarningOutlined,
  threat_actor: AlertOutlined,
  onion_service: LockOutlined,
  organization: BankOutlined,
  court_decision: AuditOutlined,
  // A regulator's public warning (corporate/finma_warnlist).
  warning_entry: WarningOutlined,
  btc_address: WalletOutlined, eth_address: WalletOutlined,
  breach: SafetyOutlined,
  malware: BugOutlined, malware_sample: BugOutlined, vt_verdict: BugOutlined,
  ip_reputation: SafetyOutlined, malicious_url: WarningOutlined,
  search_link: LinkOutlined,
  keyword: SearchOutlined,
  service: ApiOutlined,
  vulnerability: BugOutlined,
  favicon_hash: PictureOutlined,
  typosquat_domain: WarningOutlined,
  image: FileImageOutlined, camera: CameraOutlined,
  seizure_notice: AlertOutlined,
  dating_profile: HeartOutlined,
  jabber_id: MessageOutlined, tox_id: MessageOutlined, session_id: MessageOutlined,
}

export function EntityIcon({ type, color, size = 15 }: { type: string; color?: string; size?: number }) {
  const Icon = MAP[type] || ApiOutlined
  return <Icon style={{ fontSize: size, color }} />
}
