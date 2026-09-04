from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode, quote
from typing import Union

import click
import jsonpickle
import requests
from click import Context
from langcodes import Language
from tldextract import tldextract
from click.core import ParameterSource

from vinetrimmer.objects import TextTrack, Title, Tracks
from vinetrimmer.objects.tracks import MenuTrack
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.utils import is_close_match
from vinetrimmer.utils.Logger import Logger

class Amazon(BaseService):
    """
    Service code for Amazon VOD (https://amazon.com) and Amazon Prime Video (https://primevideo.com).

    \b
    Authorization: Cookies
    Security: UHD@L1 FHD@L3(ChromeCDM) SD@L3, Maintains their own license server like Netflix, be cautious.

    \b
    Region is chosen automatically based on domain extension found in cookies.
    Prime Video specific code will be run if the ASIN is detected to be a prime video variant.
    Use 'Amazon Video ASIN Display' for Tampermonkey addon for ASIN
    https://greasyfork.org/en/scripts/381997-amazon-video-asin-display
    
    vt dl --list -z uk -q 1080 Amazon B09SLGYLK8 
    """

    ALIASES = ["AMZN", "amazon"]
    TITLE_RE = r"^(?:https?://(?:www\.)?(?P<domain>amazon\.(?P<region>com|co\.uk|de|co\.jp)|primevideo\.com)(?:/.+)?/)?(?P<id>[A-Z0-9]{10,}|amzn1\.dv\.gti\.[a-f0-9-]+)"  # noqa: E501

    REGION_TLD_MAP = {
        "au": "com.au",
        "br": "com.br",
        "jp": "co.jp",
        "mx": "com.mx",
        "tr": "com.tr",
        "gb": "co.uk",
        "us": "com",
    }
    VIDEO_RANGE_MAP = {
        "SDR": "None",
        "HDR10": "Hdr10",
        "DV": "DolbyVision",
    }

    @staticmethod
    @click.command(name="Amazon", short_help="https://amazon.com, https://primevideo.com", help=__doc__)
    @click.argument("title", type=str, required=False)
    @click.option("-b", "--bitrate", default="CBR",
                  type=click.Choice(["CVBR", "CBR", "CVBR+CBR"], case_sensitive=False),
                  help="Video Bitrate Mode to download in. CVBR=Constrained Variable Bitrate, CBR=Constant Bitrate.")
    @click.option("-c", "--cdn", default=None, type=str,
                  help="CDN to download from, defaults to the CDN with the highest weight set by Amazon.")
    # UHD, HD, SD. UHD only returns HEVC, ever, even for <=HD only content
    @click.option("-vq", "--vquality", default="HD",
                  type=click.Choice(["SD", "HD", "UHD"], case_sensitive=False),
                  help="Manifest quality to request.")
    @click.option("-s", "--single", is_flag=True, default=False,
                  help="Force single episode/season instead of getting series ASIN.")
    @click.option("-am", "--amanifest", default="H265",
                  type=click.Choice(["CVBR", "CBR", "H265"], case_sensitive=False),
                  help="Manifest to use for audio. Defaults to H265 if the video manifest is missing 640k audio.")
    @click.option("-aq", "--aquality", default="SD",
                  type=click.Choice(["SD", "HD", "UHD"], case_sensitive=False),
                  help="Manifest quality to request for audio. Defaults to the same as --quality.")
    @click.pass_context
    def cli(ctx, **kwargs):
        return Amazon(ctx, **kwargs)

    def __init__(self, ctx, title, bitrate: str, cdn: str, vquality: str, single: bool,
                 amanifest: str, aquality: str):
        m = self.parse_title(ctx, title)
        self.bitrate = bitrate
        self.bitrate_source = ctx.get_parameter_source("bitrate")
        self.cdn = cdn
        self.vquality = vquality
        self.vquality_source = ctx.get_parameter_source("vquality")
        self.single = single
        self.amanifest = amanifest
        self.aquality = aquality
        super().__init__(ctx)

        assert ctx.parent is not None

        self.vcodec = ctx.parent.params["vcodec"] or "H264"
        self.range = ctx.parent.params["range_"] or "SDR"
        self.chapters_only = ctx.parent.params["chapters_only"]
        self.atmos = ctx.parent.params["atmos"]
        self.quality = ctx.parent.params.get("quality") or 1080

        self.cdm = ctx.obj.cdm
        self.profile = ctx.obj.profile

        self.region: dict[str, str] = {}
        self.endpoints: dict[str, str] = {}
        self.device: dict[str, str] = {}

        self.pv = False
        self.device_token = None
        self.device_id: None
        self.customer_id = None
        self.client_id = "f22dbddb-ef2c-48c5-8876-bed0d47594fd"  # browser client id

        if self.vquality_source != ParameterSource.COMMANDLINE:
            if 0 < self.quality <= 576 and self.range == "SDR":
                self.log.info(" + Setting manifest quality to SD")
                self.vquality = "SD"

            if self.quality > 1080:
                self.log.info(" + Setting manifest quality to UHD to be able to get 2160p video track")
                self.vquality = "UHD"

        self.vquality = self.vquality or "HD"

        if self.bitrate_source != ParameterSource.COMMANDLINE:
            if self.vcodec == "H265" and self.range == "SDR" and self.bitrate != "CVBR+CBR":
                self.bitrate = "CVBR+CBR"
                self.log.info(" + Changed bitrate mode to CVBR+CBR to be able to get H.265 SDR video track")

            if self.vquality == "UHD" and self.range != "SDR" and self.bitrate != "CBR":
                self.bitrate = "CBR"
                self.log.info(f" + Changed bitrate mode to CBR to be able to get highest quality UHD {self.range} video track")

        self.orig_bitrate = self.bitrate

        self.configure()

    # Abstracted functions

    def get_titles(self):
        res = self.session.get(
            url=self.endpoints["details"],
            params={
                "titleID": self.title,
                "isElcano": "1",
                "sections": ["Atf", "Btf"]
            },
            headers={
                "Accept": "application/json"
            }
        )

        if not res.ok:
            raise self.log.exit(f"Unable to get title: {res.text} [{res.status_code}]")

        data = res.json()["widgets"]
        product_details = data.get("productDetails", {}).get("detail")

        if not product_details:
            error = res.json()["degradations"][0]
            raise self.log.exit(f"Unable to get title: {error['message']} [{error['code']}]")

        titles = []

        if data["pageContext"]["subPageType"] == "Movie":
            card = data["productDetails"]["detail"]
            titles.append(Title(
                id_=card["catalogId"],
                type_=Title.Types.MOVIE,
                name=product_details["title"],
                #year=card["releaseYear"],
                year=card.get("releaseYear", ""),
                # language is obtained afterward
                original_lang=None,
                source=self.ALIASES[0],
                service_data=card
            ))
        else:
            if not data["titleContent"]:
                episodes = data["episodeList"]["episodes"]
                for episode in episodes:
                    details = episode["detail"]
                    titles.append(
                        Title(
                            id_=details["catalogId"],
                            type_=Title.Types.TV,
                            name=product_details["parentTitle"],
                            season=data["productDetails"]["detail"]["seasonNumber"],
                            episode=episode["self"]["sequenceNumber"],
                            episode_name=details["title"],
                            # language is obtained afterward
                            original_lang=None,
                            source=self.ALIASES[0],
                            service_data=details,
                        )
                    )
                if len(titles) == 25:
                    page_count = 1
                    pagination_data = data.get('episodeList', {}).get('actions', {}).get('pagination', [])
                    token = next((quote(item.get('token')) for item in pagination_data if item.get('tokenType') == 'NextPage'), None)
                    while True:
                        page_count += 1
                        res = self.session.get(
                            url=self.endpoints["getDetailWidgets"],
                            params={
                                "titleID": self.title,
                                "isTvodOnRow": "1",
                                "widgets": f'[{{"widgetType":"EpisodeList","widgetToken":"{token}"}}]'
                            },
                            headers={
                                "Accept": "application/json"
                            }
                        ).json()
                        episodeList = res['widgets'].get('episodeList', {})
                        for item in episodeList.get('episodes', []):
                            episode = int(item.get('self', {}).get('sequenceNumber', {}))
                            titles.append(Title(
                                id_=item["detail"]["catalogId"],
                                type_=Title.Types.TV,
                                name=product_details["parentTitle"],
                                season=product_details["seasonNumber"],
                                episode=episode,
                                episode_name=item["detail"]["title"],
                                # language is obtained afterward
                                original_lang=None,
                                source=self.ALIASES[0],
                                service_data=item
                            ))
                        pagination_data = res['widgets'].get('episodeList', {}).get('actions', {}).get('pagination', [])
                        token = next((quote(item.get('token')) for item in pagination_data if item.get('tokenType') == 'NextPage'), None)
                        if not token:
                            break
            else:
                cards = [
                    x["detail"]
                    for x in data["titleContent"][0]["cards"]
                        if not self.single or
                           (self.single and self.title in data["self"]["asins"]) or (self.single and self.title in data["self"]["compactGTI"]) or
                           (self.single and self.title in x["self"]["asins"]) or (self.single and self.title == x["detail"]["catalogId"])
                ]
                for card in cards:
                    episode_number = card.get("episodeNumber", 0)
                    if episode_number != 0:
                        titles.append(Title(
                            id_=card["catalogId"],
                            type_=Title.Types.TV,
                            name=product_details["parentTitle"],
                            season=product_details["seasonNumber"],
                            episode=episode_number,
                            episode_name=card["title"],
                            # language is obtained afterward
                            original_lang=None,
                            source=self.ALIASES[0],
                            service_data=card
                        ))
            
            if not self.single:
                temp_title = self.title
                temp_single = self.single
            
                self.single = True
                for season in data.get('seasonSelector', []):
                    season_link = season["seasonLink"]
                    match = re.search(r'/([a-zA-Z0-9]+)\/ref=', season_link)    #extract other season id using re 
                    if match:
                        extracted_value = match.group(1)
                        if data["self"]["compactGTI"] == extracted_value:   #skip entered asin season data and grab rest id's
                            continue
                        
                        self.title = extracted_value
                        for title in self.get_titles():
                            titles.append(title)
            
                self.title = temp_title
                self.single = temp_single


        if titles:
            # TODO: Needs playback permission on first title, title needs to be available
            original_lang = self.get_original_language(self.get_manifest(
                next((x for x in titles if x.type == Title.Types.MOVIE or x.episode > 0), titles[0]),
                video_codec=self.vcodec,
                bitrate_mode=self.bitrate,
                quality=self.vquality,
                ignore_errors=True
            ))
            if original_lang:
                for title in titles:
                    title.original_lang = Language.get(original_lang)
            else:
                #self.log.warning(" - Unable to obtain the title's original language, setting 'en' default...")
                for title in titles:
                    title.original_lang = Language.get("en")

        filtered_titles = []
        season_episode_count = defaultdict(int)
        for title in titles:
            key = (title.season, title.episode) 
            if season_episode_count[key] < 1:
                filtered_titles.append(title)
                season_episode_count[key] += 1

        titles = filtered_titles

        return titles

    def get_tracks(self, title: Title) -> Tracks:
        tracks = Tracks()
        if self.chapters_only:
            return []

        manifest, chosen_manifest, tracks = self.get_best_quality(title)

        manifest = self.get_manifest(
            title,
            video_codec=self.vcodec,
            bitrate_mode=self.bitrate,
            quality=self.vquality,
            hdr=self.range,
            ignore_errors=False
            
        )
        
        # Move rightsException termination here so that script can attempt continuing
        if "rightsException" in manifest["returnedTitleRendition"]["selectedEntitlement"]:
            self.log.error(" - The profile used does not have the rights to this title.")
            return

        self.customer_id = manifest["returnedTitleRendition"]["selectedEntitlement"]["grantedByCustomerId"]

        default_url_set = manifest["playbackUrls"]["urlSets"][manifest["playbackUrls"]["defaultUrlSetId"]]
        encoding_version = default_url_set["urls"]["manifest"]["encodingVersion"]
        self.log.info(f" + Detected encodingVersion={encoding_version}")

        chosen_manifest = self.choose_manifest(manifest, self.cdn)

        if not chosen_manifest:
            raise self.log.exit(f"No manifests available")

        manifest_url = self.clean_mpd_url(chosen_manifest["avUrlInfoList"][0]["url"], False)
        self.log.debug(manifest_url)
        self.log.info(" + Downloading Manifest")

        if chosen_manifest["streamingTechnology"] == "DASH":
            tracks = Tracks([
                x for x in iter(Tracks.from_mpd(
                    url=manifest_url,
                    session=self.session,
                    source=self.ALIASES[0],
                ))
            ])
        elif chosen_manifest["streamingTechnology"] == "SmoothStreaming":
            tracks = Tracks([
                x for x in iter(Tracks.from_ism(
                    url=manifest_url,
                    session=self.session,
                    source=self.ALIASES[0],
                ))
            ])
        else:
            raise self.log.exit(f"Unsupported manifest type: {chosen_manifest['streamingTechnology']}")

        need_separate_audio = ((self.aquality or self.vquality) != self.vquality
                               or self.amanifest == "CVBR" and (self.vcodec, self.bitrate) != ("H264", "CVBR")
                               or self.amanifest == "CBR" and (self.vcodec, self.bitrate) != ("H264", "CBR")
                               or self.amanifest == "H265" and self.vcodec != "H265"
                               or self.amanifest != "H265" and self.vcodec == "H265")

        if not need_separate_audio:
            audios = defaultdict(list)
            for audio in tracks.audios:
                audios[audio.language].append(audio)

            for lang in audios:
                if not any((x.bitrate or 0) >= 640000 for x in audios[lang]):
                    need_separate_audio = True
                    break

        if need_separate_audio and not self.atmos:
            manifest_type = self.amanifest or "H265"
            self.log.info(f"Getting audio from {manifest_type} manifest for potential higher bitrate or better codec")
            audio_manifest = self.get_manifest(
                title=title,
                video_codec="H265" if manifest_type == "H265" else "H264",
                bitrate_mode="CVBR" if manifest_type != "CBR" else "CBR",
                quality=self.aquality or self.vquality,
                hdr=None,
                ignore_errors=True
            )
            if not audio_manifest:
                self.log.warning(f" - Unable to get {manifest_type} audio manifests, skipping")
            elif not (chosen_audio_manifest := self.choose_manifest(audio_manifest, self.cdn)):
                self.log.warning(f" - No {manifest_type} audio manifests available, skipping")
            else:
                audio_mpd_url = self.clean_mpd_url(chosen_audio_manifest["avUrlInfoList"][0]["url"], optimise=False)
                self.log.debug(audio_mpd_url)
                self.log.info(" + Downloading HEVC manifest")

                try:
                    audio_mpd = Tracks([
                        x for x in iter(Tracks.from_mpd(
                            url=audio_mpd_url,
                            session=self.session,
                            source=self.ALIASES[0],
                        ))
                    ])
                except KeyError:
                    self.log.warning(f" - Title has no {self.amanifest} stream, cannot get higher quality audio")
                else:
                    tracks.add(audio_mpd.audios, warn_only=True)  # expecting possible dupes, ignore

        need_uhd_audio = self.atmos

        if not self.amanifest and ((self.aquality == "UHD" and self.vquality != "UHD") or not self.aquality):
            audios = defaultdict(list)
            for audio in tracks.audios:
                audios[audio.language].append(audio)
            for lang in audios:
                if not any((x.bitrate or 0) >= 640000 for x in audios[lang]):
                    need_uhd_audio = True
                    break

        if need_uhd_audio and (self.config.get("device") or {}).get(self.profile, None):
            self.log.info("Getting audio from UHD manifest for potential higher bitrate or better codec")
            temp_device = self.device
            temp_device_token = self.device_token
            temp_device_id = self.device_id
            uhd_audio_manifest = None

            try:
                if self.quality < 2160:
                    self.log.info(f" + Switching to device to get UHD manifest")
                    self.register_device()

                uhd_audio_manifest = self.get_manifest(
                    title=title,
                    video_codec="H265",
                    bitrate_mode="CVBR+CBR",
                    quality="UHD",
                    hdr="DV",  # Needed for 576kbps Atmos sometimes
                    ignore_errors=True
                )
            except:
                pass

            self.device = temp_device
            self.device_token = temp_device_token
            self.device_id = temp_device_id

            if not uhd_audio_manifest:
                self.log.warning(f" - Unable to get UHD manifests, skipping")
            elif not (ch
