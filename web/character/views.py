"""
Views for our character app
__init__.py for character configures cloudinary
"""
import json

import cloudinary
import cloudinary.forms
import cloudinary.uploader
from cloudinary import api
from cloudinary.forms import cl_init_js_callbacks
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.db.models import Q, F
from django.http import Http404, HttpResponseRedirect, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView, DetailView, CreateView
from evennia.objects.models import ObjectDB

from commands.commands import roster
from server.utils.name_paginator import NamePaginator
from server.utils.view_mixins import LimitPageMixin
from typeclasses.characters import Character
from world.dominion.models import Organization, CrisisAction
from .forms import (PhotoForm, PhotoDirectForm, PhotoUnsignedDirectForm, PortraitSelectForm,
                    PhotoDeleteForm, PhotoEditForm, FlashbackPostForm, FlashbackCreateForm)
from .models import Photo, Story, Episode, Chapter, Flashback, ClueDiscovery, DISCO_MULT


def get_character_from_ob(object_id):
    """Helper function to get a character, run checks, return character + error messages"""
    return get_object_or_404(Character, id=object_id)


def comment(request, object_id):
    """
    Makes an in-game comment on a character sheet.
    """
    send_charob = request.user.db.char_ob
    rec_charob = get_character_from_ob(object_id)
    comment_txt = request.POST['comment']
    roster.create_comment(send_charob, rec_charob, comment_txt)
    return HttpResponseRedirect(reverse('character:sheet', args=(object_id,)))


def sheet(request, object_id):
    """
    Displays a character sheet, and is used as the primary
    'wiki' page for a character.
    """
    character = get_character_from_ob(object_id)
    user = request.user
    show_hidden = False
    can_comment = False
    # we allow only staff or the player to see secret information
    # but only other characters can leave IC comments.
    if user.is_authenticated():
        try:
            if user.char_ob.id == character.id or user.check_permstring("builders"):
                show_hidden = True
            if user.char_ob.id != character.id:
                can_comment = True
        # if we're logged in as a player without a character assigned somehow
        except AttributeError:
            pass
    if not show_hidden and (hasattr(character, 'roster') and
                            character.roster.roster.name == "Unavailable"):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    pheight = character.db.portrait_height or 480
    pwidth = character.db.portrait_width or 320
    try:
        fealty_org_id = Organization.objects.get(name__iexact=character.db.fealty)
    except Organization.DoesNotExist:
        fealty_org_id = None
    try:
        family_org_id = Organization.objects.get(name__iexact=character.db.family)
    except Organization.DoesNotExist:
        family_org_id = None
    return render(request, 'character/sheet.html', {'character': character,
                                                    'show_hidden': show_hidden,
                                                    'can_comment': can_comment,
                                                    'pheight': pheight,
                                                    'pwidth': pwidth,
                                                    'fealty_org_id': fealty_org_id,
                                                    'family_org_id': family_org_id,
                                                    'page_title': character.key})


def journals(request, object_id):
    """
    Displays a character's journals
    """
    character = get_character_from_ob(object_id)
    user = request.user
    show_hidden = False
    if user.is_authenticated():
        if user.char_ob.id == character.id or user.check_permstring("builders"):
            show_hidden = True
    if not show_hidden and (hasattr(character, 'roster') and
                            character.roster.roster.name == "Unavailable"):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    white_journal = character.messages.white_journal
    black_journal = character.messages.black_journal

    return render(request, 'character/journals.html', {'character': character,
                                                       'show_hidden': show_hidden,
                                                       'white_journal': white_journal,
                                                       'black_journal': black_journal,
                                                       'page_title': '%s Journals' % character.key
                                                       })

API_CACHE = None


def character_list(request):
    """View for API call from wikia"""
    def get_relations(char):
        """helper function for getting dict of character's relationships"""
        def parse_name(relation):
            """Helper function for outputting string display of character name"""
            if relation.player:
                char_ob = relation.player.char_ob
                return "%s %s" % (char_ob.key, char_ob.db.family)
            else:
                return str(relation)
        try:
            dom = char.player_ob.Dominion
            parents = []
            uncles_aunts = []
            for parent in dom.all_parents:
                parents.append(parent)
                for sibling in parent.siblings:
                    uncles_aunts.append(sibling)
                    for spouse in sibling.spouses.all():
                        uncles_aunts.append(spouse)

            unc_or_aunts = set(uncles_aunts)
            relations = {
                'parents': [parse_name(ob) for ob in parents],
                'siblings': list(parse_name(ob) for ob in dom.siblings),
                'uncles_aunts': list(parse_name(ob) for ob in unc_or_aunts),
                'cousins': list(parse_name(ob) for ob in dom.cousins)
            }
            return relations
        except AttributeError:
            return {}

    def get_dict(char):
        """Helper function for getting dict of all relevant character information"""
        character = {}
        if char.player_ob.is_staff or char.db.npc:
            return character
        character = {
            'name': char.key,
            'social_rank': char.db.social_rank,
            'fealty': char.db.fealty,
            'house': char.db.family,
            'relations': get_relations(char),
            'gender': char.db.gender,
            'age': char.db.age,
            'religion': char.db.religion,
            'vocation': char.db.vocation,
            'height': char.db.height,
            'hair_color': char.db.haircolor,
            'eye_color': char.db.eyecolor,
            'skintone': char.db.skintone,
            'description': char.perm_desc,
            'personality': char.db.personality,
            'background': char.db.background,
            'status': char.roster.roster.name,
            'longname': char.db.longname
        }
        try:
            if char.portrait:
                character['image'] = char.portrait.image.url
        except (Photo.DoesNotExist, AttributeError):
            pass
        return character
    global API_CACHE
    if not API_CACHE:
        ret = map(get_dict, Character.objects.filter(Q(roster__roster__name="Active") |
                                                     Q(roster__roster__name="Available")))
        API_CACHE = json.dumps(ret)
    return HttpResponse(API_CACHE, content_type='application/json')


class RosterListView(ListView):
    """Base View for listing all the characters in the roster. Will be overridden for different rosters"""
    model = ObjectDB
    template_name = 'character/list.html'
    paginator_class = NamePaginator
    paginate_by = 20
    roster_name = "Active"

    def get_queryset(self):
        """Gets queryset of Character objects"""
        return ObjectDB.objects.filter(roster__roster__name=self.roster_name).order_by('db_key')

    # noinspection PyBroadException
    def get_context_data(self, **kwargs):
        """Gets context for template. Permission to see secret stuff is in show_secret"""
        context = super(RosterListView, self).get_context_data(**kwargs)
        user = self.request.user
        show_hidden = False
        try:
            if user.is_authenticated() and user.check_permstring("builders"):
                show_hidden = True
        except Exception:
            import traceback
            traceback.print_exc()
        context['show_hidden'] = show_hidden
        context['roster_name'] = self.roster_name
        context['page_title'] = "%s Roster" % self.roster_name
        return context


class ActiveRosterListView(RosterListView):
    """View for list of active characters"""
    pass


class AvailableRosterListView(RosterListView):
    """View for list of Available characters"""
    roster_name = "Available"


class GoneRosterListView(RosterListView):
    """View for list of dead characters. RIP"""
    roster_name = "Gone"


class IncompleteRosterListView(RosterListView):
    """View for list of characters that are in the process of being created"""
    roster_name = "Incomplete"

    def get_queryset(self):
        """Only grant permission to see for staff"""
        user = self.request.user
        if not (user.is_authenticated() and user.check_permstring("builders")):
            raise Http404("Not staff")
        return super(IncompleteRosterListView, self).get_queryset()


class UnavailableRosterListView(IncompleteRosterListView):
    """List of characters that cannot be seen/removed from play. NPCs and others that aren't visible"""
    roster_name = "Unavailable"


class InactiveRosterListView(IncompleteRosterListView):
    """List of characters that are not presently active but could return"""
    roster_name = "Inactive"


def gallery(request, object_id):
    """"List photos that belong to object_id"""
    character = get_character_from_ob(object_id)
    user = request.user
    can_upload = False
    if user.is_authenticated() and (user.db.char_ob == character or user.is_staff):
        can_upload = True
    photos = Photo.objects.filter(owner__id=object_id)
    portrait_form = PortraitSelectForm(object_id)
    edit_form = PhotoEditForm(object_id)
    delete_form = PhotoDeleteForm(object_id)
    pheight = character.db.portrait_height or 480
    pwidth = character.db.portrait_width or 320
    return render(request, 'character/gallery.html', {'character': character, 'photos': photos,
                                                      'can_upload': can_upload, 'portrait_form': portrait_form,
                                                      'edit_form': edit_form, 'delete_form': delete_form,
                                                      'pheight': pheight, 'pwidth': pwidth,
                                                      'page_title': 'Gallery: %s' % character.key
                                                      })


def edit_photo(request, object_id):
    """View for changing a photo"""
    character = get_character_from_ob(object_id)
    user = request.user
    if not (user == character.player_ob or user.is_staff):
        raise Http404("Only owners or staff may edit photos.")
    try:
        photo = Photo.objects.get(pk=request.POST['select_photo'])
        title = request.POST['title']
        alt_text = request.POST['alt_text']
    except Exception as err:
        raise Http404(err)
    photo.title = title
    photo.alt_text = alt_text
    photo.save()
    if character.db.portrait and character.db.portrait.id == photo.id:
        character.db.portrait = photo
    return HttpResponseRedirect(reverse('character:gallery', args=(object_id,)))


def delete_photo(request, object_id):
    """View for deleting a photo. Calls cloudinary.api to delete it from storage, model deleted after"""
    character = get_character_from_ob(object_id)
    user = request.user
    if not (user == character.player_ob or user.is_staff):
        raise Http404("Only owners or staff may delete photos.")
    try:
        photo = Photo.objects.get(pk=request.POST['select_photo'])
    except Exception as err:
        raise Http404(err)
    cloudinary.api.delete_resources([photo.image.public_id])
    if character.db.portrait and character.db.portrait.id == photo.id:
        character.db.portrait = None
    photo.delete()
    return HttpResponseRedirect(reverse('character:gallery', args=(object_id,)))


def select_portrait(request, object_id):
    """
    Chooses a photo as character portrait
    """
    character = get_character_from_ob(object_id)
    try:
        portrait = Photo.objects.get(pk=request.POST['select_portrait'])
        height = request.POST['portrait_height']
        width = request.POST['portrait_width']
    except (Photo.DoesNotExist, KeyError, AttributeError):
        portrait = None
        height = None
        width = None
    character.db.portrait_height = height or 480
    character.db.portrait_width = width or 320
    try:
        character.roster.profile_picture = portrait
        character.roster.save()
    except AttributeError:
        pass
    return HttpResponseRedirect(reverse('character:gallery', args=(object_id,)))


def upload(request, object_id):
    """View for uploading new photo resource to cloudinary and creating model"""
    user = request.user
    character = get_character_from_ob(object_id)
    if not user.is_authenticated() or (user.db.char_ob != character and not user.is_staff):
        raise Http404("You are not permitted to upload to this gallery.")
    unsigned = request.GET.get("unsigned") == "true"

    if unsigned:
        # For the sake of simplicity of the sample site, we generate the preset on the fly.
        #  It only needs to be created once, in advance.
        try:
            api.upload_preset(PhotoUnsignedDirectForm.upload_preset_name)
        except api.NotFound:
            api.create_upload_preset(name=PhotoUnsignedDirectForm.upload_preset_name, unsigned=True,
                                     folder="preset_folder")

    direct_form = PhotoUnsignedDirectForm() if unsigned else PhotoDirectForm()
    context = dict(
        # Form demonstrating backend upload
        backend_form=PhotoForm(),
        # Form demonstrating direct upload
        direct_form=direct_form,
        # Should the upload form be unsigned
        unsigned=unsigned,
    )
    # When using direct upload - the following call in necessary to update the
    # form's callback url
    cl_init_js_callbacks(context['direct_form'], request)
    context['character'] = character
    context['page_title'] = 'Upload'
    if request.method == 'POST':
        # Only backend upload should be posting here
        owner_char = Photo(owner=character)
        form = PhotoForm(request.POST, request.FILES, instance=owner_char)
        context['posted'] = False
        if form.is_valid():
            # Uploads image and creates a model instance for it
            if user.is_authenticated() and user.check_permstring("builders"):
                context['show_hidden'] = True
            context['posted'] = form.instance
            form.save()

    return render(request, 'character/upload.html', context)


@csrf_exempt
def direct_upload_complete(request, object_id):
    """View for uploading to cloudinary with javascript widget"""
    character = get_character_from_ob(object_id)
    owner_char = Photo(owner=character)
    form = PhotoDirectForm(request.POST, instance=owner_char)
    if form.is_valid():
        # Create a model instance for uploaded image using the provided data
        form.save()
        ret = dict(photo_id=form.instance.id)
    else:
        ret = dict(errors=form.errors)

    return HttpResponse(json.dumps(ret), content_type='application/json')


class ChapterListView(ListView):
    """View for listing chapters in a current story"""
    model = Chapter
    template_name = 'character/story.html'

    @property
    def story(self):
        """Gets the story for the chapters"""
        get = self.request.GET
        if not get:
            return Story.objects.latest('start_date')
        story_name = get.get('story_name', "")
        return Story.objects.get(name=story_name)

    def get_queryset(self):
        """QuerySet is all chapters for the current story"""
        return Chapter.objects.filter(story=self.story).order_by('-start_date')

    @property
    def viewable_crises(self):
        """Gets queryset of crises visible to user"""
        from world.dominion.models import Crisis
        return Crisis.objects.viewable_by_player(self.request.user).filter(chapter__in=self.get_queryset())

    def get_context_data(self, **kwargs):
        """Gets context for our template. Stories, current story, and viewable_crises"""
        context = super(ChapterListView, self).get_context_data(**kwargs)
        story = self.story
        context['story'] = story
        context['page_title'] = str(story)
        context['viewable_crises'] = self.viewable_crises
        context['all_stories'] = Story.objects.all().order_by('-start_date')
        return context


def episode(request, ep_id):
    """View for displaying a specific episode in a chapter"""
    new_episode = get_object_or_404(Episode, id=ep_id)
    crisis_updates = new_episode.get_viewable_crisis_updates_for_player(request.user)
    emits = new_episode.get_viewable_emits_for_player(request.user)
    return render(request, 'character/episode.html', {'episode': new_episode,
                                                      'updates': crisis_updates,
                                                      'emits': emits,
                                                      'page_title': str(new_episode)})


class ActionListView(ListView):
    """View for listing the CrisisActions of a given character"""
    model = CrisisAction
    template_name = "character/actions.html"

    @property
    def character(self):
        """The main character of the actions"""
        return get_object_or_404(Character, id=self.kwargs['object_id'])

    def get_queryset(self):
        """Display only public actions if we're not staff or a participant"""
        qs = self.character.past_participated_actions.order_by('-date_submitted')
        user = self.request.user
        if not user or not user.is_authenticated():
            return qs.filter(public=True)
        if user.is_staff or user.check_permstring("builders") or user.char_ob == self.character:
            return qs
        return qs.filter(public=True)

    def get_context_data(self, **kwargs):
        """Gets context for the template"""
        context = super(ActionListView, self).get_context_data(**kwargs)
        context['character'] = self.character
        return context


class CharacterMixin(object):
    """Mixin for adding self.character to flashback views"""
    @property
    def character(self):
        """Main character for the flashback"""
        return get_object_or_404(Character, id=self.kwargs['object_id'])

    def get_context_data(self, **kwargs):
        """Gets context for template"""
        context = super(CharacterMixin, self).get_context_data(**kwargs)
        context['character'] = self.character
        return context


class FlashbackListView(CharacterMixin, ListView):
    """View for listing flashbacks"""
    model = Flashback
    template_name = "character/flashback_list.html"

    def get_queryset(self):
        """Ensure flashbacks are private to participants/staff"""
        user = self.request.user
        if not user or not user.is_authenticated():
            raise PermissionDenied
        if user.char_ob != self.character and not (user.is_staff or user.check_permstring("builders")):
            raise PermissionDenied
        entry = self.character.roster
        return Flashback.objects.filter(Q(owner=entry) | Q(allowed=entry)).distinct()


class FlashbackCreateView(CharacterMixin, CreateView):
    """View for creating a flashback"""
    model = Flashback
    template_name = "character/flashback_create_form.html"
    form_class = FlashbackCreateForm

    def get_form_kwargs(self):
        """Gets special kwargs for our form. We pass along the owner to save"""
        kwargs = super(FlashbackCreateView, self).get_form_kwargs()
        kwargs['owner'] = self.character.roster
        return kwargs

    def get_context_data(self, **kwargs):
        """Checks permission to create a flashback then returns context"""
        try:
            user = self.request.user
            if user != self.character.player_ob and not (user.is_staff or user.check_permstring("builders")):
                raise PermissionDenied
        except AttributeError:
            raise PermissionDenied
        return super(FlashbackCreateView, self).get_context_data(**kwargs)

    def get_success_url(self):
        """Gets the URL to redirect us to on a successful submission"""
        return reverse('character:list_flashbacks', kwargs={'object_id': self.character.id})

    def form_valid(self, form):
        """Update newly created flashback with our owner and return appropriate response"""
        response = super(FlashbackCreateView, self).form_valid(form)
        self.object.owner = self.character.roster
        self.object.save()
        return response


class FlashbackAddPostView(CharacterMixin, DetailView):
    """View for an individual flashback or adding a post to it"""
    model = Flashback
    form_class = FlashbackPostForm
    template_name = "character/flashbackpost_form.html"
    pk_url_kwarg = 'flashback_id'

    @property
    def poster(self):
        """RosterEntry of user who will be making post"""
        try:
            return self.request.user.roster
        except AttributeError:
            return None

    def get_context_data(self, **kwargs):
        """Gets context for template, ensures we have permissions"""
        context = super(FlashbackAddPostView, self).get_context_data(**kwargs)
        user = self.request.user
        if user not in self.get_object().all_players and not (user.is_staff or user.check_permstring("builders")):
            raise PermissionDenied
        context['form'] = FlashbackPostForm()
        return context

    # noinspection PyUnusedLocal
    def post(self, request, *args, **kwargs):
        """Handles POST request. Processes doing a post to the flashback"""
        if "add_post" in request.POST:
            form = FlashbackPostForm(request.POST)
            if form.is_valid():
                # write journal
                form.add_post(self.get_object(), self.poster)
            else:
                raise Http404(form.errors)
        return HttpResponseRedirect(reverse('character:flashback_post', kwargs={'object_id': self.character.id,
                                                                                'flashback_id': self.get_object().id}))


class KnownCluesView(CharacterMixin, LimitPageMixin, ListView):
    model = ClueDiscovery
    template_name = "character/clue_list.html"
    paginate_by = 10

    def search_filters(self, queryset):
        get = self.request.GET
        if not get:
            return queryset
        text = get.get('search_text')
        if text:
            queryset = queryset.filter(
                Q(clue__desc__icontains=text) |
                Q(clue__name__icontains=text) |
                Q(message__icontains=text)
            )
        return queryset

    def get_queryset(self):
        """Ensure flashbacks are private to participants/staff"""
        user = self.request.user
        if not user or not user.is_authenticated():
            raise PermissionDenied
        if user.char_ob != self.character and not (user.is_staff or user.check_permstring("builders")):
            raise PermissionDenied
        entry = self.character.roster
        qs = entry.finished_clues.order_by('id')
        return self.search_filters(qs)

    def get_context_data(self, **kwargs):
        """Gets our context - do special stuff to preserve search tags through pagination"""
        context = super(KnownCluesView, self).get_context_data(**kwargs)
        # paginating our read journals as well as unread
        search_tags = ""
        search_text = self.request.GET.get('search_text', None)
        if search_text:
            search_tags += "&search_text=%s" % search_text
        context['search_tags'] = search_tags
        context['page_title'] = "%s - Known Clues" % self.character.name
        return context
